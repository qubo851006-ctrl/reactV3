"""
案件台账相关辅助函数，从 training-manager/app.py 拆出。
"""
import gc
import re
import os
import json
import base64
import logging
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from llm_client import get_llm_client, build_ai_http_headers
from config import MODEL_CHAT, LEDGER_JSON_PATH, LEDGER_OUTPUT_DIR, LEGAL_ARCHIVE_ROOT
from config import AIRCHINA_API_KEY, AIRCHINA_BASE_URL, AI_HTTP_VERIFY_SSL
from file_store import atomic_write_bytes, atomic_write_text, file_lock
from model_routes import resolve_vision_model
from upload_validation import safe_upload_name


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


LEDGER_DOC_CONCURRENCY = _env_positive_int("LEDGER_DOC_CONCURRENCY", 3)
LEDGER_LLM_CONCURRENCY = _env_positive_int("LEDGER_LLM_CONCURRENCY", 3)
LEDGER_OCR_CONCURRENCY = _env_positive_int("LEDGER_OCR_CONCURRENCY", 2)
AIRCHINA_OCR_TIMEOUT_SECONDS = _env_positive_float("AIRCHINA_OCR_TIMEOUT_SECONDS", 12.0)
AIRCHINA_OCR_FAILURE_THRESHOLD = _env_positive_int("AIRCHINA_OCR_FAILURE_THRESHOLD", 3)
AIRCHINA_OCR_BREAKER_SECONDS = _env_positive_float("AIRCHINA_OCR_BREAKER_SECONDS", 90.0)
_AIRCHINA_OCR_CHANNEL = os.getenv("AIRCHINA_OCR_CHANNEL", "25")

_AIRCHINA_BREAKER_LOCK = threading.Lock()
_AIRCHINA_FAILURES = 0
_AIRCHINA_OPEN_UNTIL = 0.0


def reset_airchina_ocr_breaker() -> None:
    global _AIRCHINA_FAILURES, _AIRCHINA_OPEN_UNTIL
    with _AIRCHINA_BREAKER_LOCK:
        _AIRCHINA_FAILURES = 0
        _AIRCHINA_OPEN_UNTIL = 0.0


def _airchina_ocr_available() -> bool:
    with _AIRCHINA_BREAKER_LOCK:
        return time.monotonic() >= _AIRCHINA_OPEN_UNTIL


def _record_airchina_success() -> None:
    global _AIRCHINA_FAILURES, _AIRCHINA_OPEN_UNTIL
    with _AIRCHINA_BREAKER_LOCK:
        _AIRCHINA_FAILURES = 0
        _AIRCHINA_OPEN_UNTIL = 0.0


def _record_airchina_failure() -> None:
    global _AIRCHINA_FAILURES, _AIRCHINA_OPEN_UNTIL
    with _AIRCHINA_BREAKER_LOCK:
        _AIRCHINA_FAILURES += 1
        if _AIRCHINA_FAILURES >= AIRCHINA_OCR_FAILURE_THRESHOLD:
            _AIRCHINA_OPEN_UNTIL = time.monotonic() + AIRCHINA_OCR_BREAKER_SECONDS


# ── 提取文书文字 ──────────────────────────────────────────────

def _strip_ocr_text(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^```\w*\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return text


def _collect_ocr_texts(value) -> list[str]:
    texts: list[str] = []
    if isinstance(value, str):
        text = _strip_ocr_text(value)
        if text:
            texts.append(text)
    elif isinstance(value, list):
        for item in value:
            texts.extend(_collect_ocr_texts(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            key_l = str(key).lower()
            if key_l in {"markdown", "text", "content"}:
                texts.extend(_collect_ocr_texts(item))
            elif isinstance(item, (dict, list)):
                texts.extend(_collect_ocr_texts(item))
    return texts


def _extract_ocr_text_from_result(result: dict) -> str:
    payload = result.get("payload", {})
    payload_result = payload.get("result", {}) if isinstance(payload, dict) else {}

    for candidate in (
        payload.get("markdown") if isinstance(payload, dict) else None,
        payload.get("text") if isinstance(payload, dict) else None,
        payload_result.get("markdown") if isinstance(payload_result, dict) else None,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return _strip_ocr_text(candidate)

    docs = payload_result.get("document", []) if isinstance(payload_result, dict) else []
    if isinstance(docs, list):
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            if str(doc.get("name", "")).lower() == "markdown":
                text = _strip_ocr_text(str(doc.get("value", "")))
                if text:
                    return text

    collected = _collect_ocr_texts(payload_result)
    return "\n".join(dict.fromkeys(collected)).strip()


def extract_file_text(file_bytes: bytes, filename: str) -> str:
    """从 PDF/DOCX/DOC 字节提取文字，PDF 优先 pdfplumber，失败则 OCR。"""
    ext = os.path.splitext(filename)[1].lower()
    text = ""
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        if ext == ".pdf":
            import pdfplumber
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text += t + "\n"
        elif ext in (".docx", ".doc"):
            from docx import Document
            doc = Document(tmp_path)
            text = "\n".join(p.text for p in doc.paragraphs)
    finally:
        os.unlink(tmp_path)
    return text.strip()


def _ocr_page_with_airchina(page_index: int, img_b64: str) -> tuple[int, str]:
    """用中航信专用 OCR 服务识别单页图片，返回 (页码, 文字)。"""
    import httpx
    import warnings

    url = AIRCHINA_BASE_URL.rstrip("/") + f"/oneapi/proxy/{_AIRCHINA_OCR_CHANNEL}/"
    headers = {
        **build_ai_http_headers(),
        "Authorization": f"Bearer {AIRCHINA_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "header": {"sid": f"ocr-{page_index}"},
        "parameter": {
            "ocr": {
                "result_option": "normal",
                "result_format": "json,markdown",
                "output_type": "one_shot",
                "exif_option": "0",
                "json_element_option": "",
                "markdown_element_option": "watermark=0,page_header=0,page_footer=0,page_number=0",
                "sed_element_option": "",
            }
        },
        "payload": {"imageData": img_b64},
    }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with httpx.Client(verify=AI_HTTP_VERIFY_SSL, timeout=AIRCHINA_OCR_TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = client.post(url, headers=headers, json=body)
    resp.raise_for_status()

    result = resp.json()
    header = result.get("header", {})
    if header.get("code") != 0:
        raise RuntimeError(f"OCR 服务错误：{header.get('message', '未知')}")

    return page_index, _extract_ocr_text_from_result(result)


def _ocr_page_with_vision(client, selected_model: str, page_index: int, img_b64: str) -> tuple[int, str]:
    """用视觉模型 OCR 单页图片（降级兜底用）。"""
    response = client.chat.completions.create(
        model=selected_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text",
                 "text": "请将图片中的所有文字原文提取出来，保持段落结构，不要添加任何说明或总结。"},
            ],
        }],
    )
    return page_index, (response.choices[0].message.content or "").strip()


def _render_pdf_to_images(pdf_bytes: bytes) -> list[tuple[int, str]]:
    """将 PDF 每页渲染为 (页码, base64 JPEG) 列表。"""
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    try:
        for idx, page in enumerate(doc):
            pix = page.get_pixmap(dpi=150)
            img_b64 = base64.b64encode(pix.tobytes("jpeg", jpg_quality=85)).decode()
            images.append((idx, img_b64))
    finally:
        doc.close()
    return images


def ocr_pdf_with_vision(pdf_bytes: bytes, model: str | None = None) -> str:
    """扫描版 PDF 文字提取：优先中航信专用 OCR（并发），失败则降级视觉模型。"""
    page_images = _render_pdf_to_images(pdf_bytes)
    if not page_images:
        return ""

    texts = [""] * len(page_images)
    max_workers = min(max(1, LEDGER_OCR_CONCURRENCY), len(page_images))

    # 优先：中航信专用 OCR
    if AIRCHINA_API_KEY and _airchina_ocr_available():
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(_ocr_page_with_airchina, idx, img_b64)
                    for idx, img_b64 in page_images
                ]
                for future in as_completed(futures):
                    idx, text = future.result()
                    texts[idx] = text
            combined = "\n".join(t for t in texts if t)
            if combined.strip():
                _record_airchina_success()
                return combined
            _record_airchina_failure()
            logging.warning("中航信 OCR 返回空文本，降级视觉模型")
        except Exception as e:
            _record_airchina_failure()
            logging.warning("中航信 OCR 失败，降级视觉模型：%s", e)
            texts = [""] * len(page_images)
    elif AIRCHINA_API_KEY:
        logging.warning("中航信 OCR 熔断中，直接降级视觉模型")

    # 降级：视觉模型
    client = get_llm_client()
    selected_model = resolve_vision_model(model)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_ocr_page_with_vision, client, selected_model, idx, img_b64)
            for idx, img_b64 in page_images
        ]
        for future in as_completed(futures):
            idx, text = future.result()
            texts[idx] = text

    return "\n".join(t for t in texts if t)


def render_pdf_pages(pdf_bytes: bytes) -> list[str]:
    """将 PDF 每页渲染为 base64 JPEG，返回有序列表（供外部逐页 OCR 使用）。"""
    return [img_b64 for _, img_b64 in _render_pdf_to_images(pdf_bytes)]


def ocr_single_page(img_b64: str, model: str | None = None) -> str:
    """OCR 单页图片：优先中航信专用 OCR，失败则降级视觉模型。"""
    if AIRCHINA_API_KEY and _airchina_ocr_available():
        try:
            _, text = _ocr_page_with_airchina(0, img_b64)
            if text.strip():
                _record_airchina_success()
                return text
            _record_airchina_failure()
            logging.warning("中航信 OCR 返回空文本，降级视觉模型")
        except Exception as e:
            _record_airchina_failure()
            logging.warning("中航信 OCR 失败，降级视觉模型：%s", e)
    elif AIRCHINA_API_KEY:
        logging.warning("中航信 OCR 熔断中，直接降级视觉模型")

    client = get_llm_client()
    selected_model = resolve_vision_model(model)
    response = client.chat.completions.create(
        model=selected_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text",
                 "text": "请将图片中的所有文字原文提取出来，保持段落结构，不要添加任何说明或总结。"},
            ],
        }],
    )
    return (response.choices[0].message.content or "").strip()


def detect_doc_type_by_content(text: str) -> str:
    """从文书内容判断文书类型。优先关键词快速匹配，匹配不到才调 LLM 兜底。"""
    if not text:
        return "其他"
    head = text[:600]

    # ── 关键词快速匹配（按优先级从高到低）──────────────────────
    if "强制执行申请书" in head or ("强制执行" in head and "申请书" in head):
        return "强制执行申请书"
    if "再审申请书" in head or ("再审" in head and "申请书" in head):
        return "再审申请书"
    # 上诉状先于起诉状匹配，避免"民事上诉状"被错匹配为起诉状
    if "上诉状" in head or "民事上诉状" in head:
        return "上诉状"
    if "起诉状" in head or "民事起诉状" in head:
        return "起诉状"
    if "一审民事判决书" in head or ("民事判决书" in head and "民初" in text[:1000]):
        return "一审判决书"
    if "二审民事判决书" in head or ("民事判决书" in head and "民终" in text[:1000]):
        return "二审判决书"
    if "民事判决书" in head or "判决书" in head:
        return "判决书"
    if "民事裁定书" in head or "裁定书" in head:
        return "裁定书"
    if "情况说明" in head or "业务情况" in head or "情况汇报" in head:
        return "业务情况说明"

    # ── LLM 兜底（关键词均未命中时）────────────────────────────
    client = get_llm_client()
    response = client.chat.completions.create(
        model=MODEL_CHAT,
        messages=[{"role": "user", "content": (
            "请判断以下文书是什么类型，只回复类型名称，从下列选项中选一个：\n"
            "起诉状、上诉状、再审申请书、一审判决书、二审判决书、判决书、裁定书、强制执行申请书、业务情况说明、其他\n\n"
            "注意：业务情况说明是公司内部撰写的案件背景说明文件，非法院正式文书。\n\n"
            f"文书内容（前500字）：\n{text[:500]}"
        )}],
        max_tokens=20,
    )
    raw = response.choices[0].message.content.strip()
    for t in ["强制执行申请书", "再审申请书", "一审判决书", "二审判决书", "裁定书", "上诉状", "起诉状", "判决书", "业务情况说明"]:
        if t in raw:
            return t
    return "其他"


# ── 字段提取 ──────────────────────────────────────────────────

PROMPT_SUSOSTATE = """你是法务专家，从以下起诉状/上诉状中提取关键信息，以JSON格式返回。

要求：
- 案号：法院受理案号，格式如"(2022)川01民初1234号"，找不到填 null
- 案件名称：格式"原告方 与 被告方 案由纠纷案"，简洁概括
- 案件发生时间：起诉/立案日期，格式 YYYY-MM-DD，找不到填 null
- 案由：如"房屋租赁合同纠纷"、"劳动争议"等
- 诉讼主体：列出所有原告、被告、第三人等全部诉讼主体，格式"原告：XX\n被告一：XX\n被告二：XX"，禁止用"等"省略主体
- 主诉被诉：填"诉讼-主诉"或"诉讼-被诉"
- 标的金额：诉讼请求的金额总计，单位万元，保留两位小数，找不到填 null
- 基本情况：以诉讼请求为主，写清请求事项、金额、期间、责任承担；不要加入法院裁判理由

只返回JSON，不要其他文字：
{"案号":null,"案件名称":"","案件发生时间":"","案由":"","诉讼主体":"","主诉被诉":"","标的金额":null,"基本情况":""}

文书内容：
{text}"""

PROMPT_JUDGMENT = """你是法务专家，从以下判决书/裁定书中提取关键信息，以JSON格式返回。

要求：
- 本案案号：本判决书的案号，如"(2023)川01民终24491号"，找不到填 null
- 关联案号：文中提到的上一审级案号（如"原审"/"一审"的案号），找不到填 null
- 法院名称：作出本判决/裁定的法院名称，找不到填 null
- 审级：根据本案案号中的字样判断，严格按以下规则填写：
  * 案号含"民初"→填"一审"
  * 案号含"民终"→填"二审"
  * 案号含"民申"或文书标题含"再审"→填"再审"
  * 实在无法判断→填"一审"
- 文书性质：如"一审判决"、"终审判决"、"民事裁定"，找不到填 null
- 生效判决日期：判决书落款日期，格式 YYYY-MM-DD，找不到填 null
- 处理结果：按企业法务案件台账口径提炼裁判主文，优先写驳回/支持/撤销/维持/改判/发回、金额、各方义务、费用承担，尽量简明；不要展开长篇裁判理由
- 后续程序：如文中提到已上诉、再审、执行、结案、回款、终审结果，写明日期、主体、法院和请求/结果；没有填 null
- 公司经济影响：如收回款项、挽回损失、保证金归属、我方需支付金额等，按管理口径简明汇总；没有填 null
- 服务律所：代理我方的律师事务所及律师姓名，找不到填 null

只返回JSON，不要其他文字：
{"本案案号":null,"关联案号":null,"法院名称":null,"审级":"","文书性质":null,"生效判决日期":"","处理结果":"","后续程序":null,"公司经济影响":null,"服务律所":null}

文书内容：
{text}"""

PROMPT_EXECUTION = """你是法务专家，从以下强制执行申请书中提取关键信息，以JSON格式返回。

只返回JSON，不要其他文字：
{"强制执行时间":null}

文书内容：
{text}"""

PROMPT_BUSINESS_DESC = """你是法务专家助手，从以下公司内部业务情况说明中提取案件背景信息，以JSON格式返回。

要求：
- 业务背景：案件涉及的合同/交易经过、争议事实及业务说明，尽量完整保留关键细节，不超过500字

只返回JSON，不要其他文字：
{"业务背景":""}

文书内容：
{text}"""

PROMPT_MERGE_SITUATION = """你是法务专家助手，请将以下"业务情况说明"和"诉讼请求"整合为一段连贯的案件基本情况描述。

要求：
- 先概述案件背景和争议事实（来自业务情况说明）
- 再列明诉讼请求具体内容（来自起诉状）
- 保留关键金额、日期等数字信息，语言简洁
- 不超过600字，不要添加标题或分节符号

业务情况说明内容：
{business_bg}

诉讼请求内容：
{litigation_claims}"""


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


_CASE_NO_RE = re.compile(r"[（(]\s*\d{4}\s*[）)]\s*[\u4e00-\u9fffA-Za-z0-9\s]{2,80}?号")


def needs_ocr_text(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    slash_tokens = len(re.findall(r"/\d+", stripped))
    return chinese_count < 20 or slash_tokens > chinese_count


def _normalize_case_no(value: str) -> str:
    return (
        str(value or "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("號", "号")
        .replace("\u3000", "")
        .strip()
    )


def _case_no_key(value: str) -> str:
    return re.sub(r"\s+", "", _normalize_case_no(value))


def _display_case_no(value: str) -> str:
    normalized = _normalize_case_no(value)
    return re.sub(r"^\((\d{4})\)", r"（\1）", normalized)


def _dedupe_case_numbers(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = _normalize_case_no(value)
        key = _case_no_key(normalized)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _extract_case_numbers_from_text(text: str) -> list[str]:
    return _dedupe_case_numbers(_CASE_NO_RE.findall(text or ""))


def _case_numbers_from_docs(docs: list | None) -> list[str]:
    if not docs:
        return []
    numbers: list[str] = []
    for doc in docs:
        numbers.extend(_extract_case_numbers_from_text(doc.get("filename", "")))
        numbers.extend(_extract_case_numbers_from_text(doc.get("text", "")))
    return _dedupe_case_numbers(numbers)


def _merge_situation_text(client, business_bg: str, litigation_claims: str) -> str:
    """将业务情况说明背景与起诉状诉讼请求合并为连贯的基本情况描述。"""
    if not business_bg:
        return litigation_claims
    if not litigation_claims:
        return business_bg
    prompt = (
        PROMPT_MERGE_SITUATION
        .replace("{business_bg}", business_bg[:3000])
        .replace("{litigation_claims}", litigation_claims[:3000])
    )
    resp = client.chat.completions.create(
        model=MODEL_CHAT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000, temperature=0.1,
    )
    return resp.choices[0].message.content.strip()


def _format_cn_date(value) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    if not match:
        return text
    year, month, day = match.groups()
    return f"{year}年{int(month)}月{int(day)}日"


def _default_doc_nature(stage: str, case_no: str = "") -> str:
    if stage == "二审":
        return "终审判决"
    if stage == "再审" or "民申" in (case_no or ""):
        return "民事裁定"
    if stage == "一审":
        return "一审判决"
    return "判决"


def _join_ledger_sentences(parts: list[str]) -> str:
    sentences: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if not text:
            continue
        if text[-1] not in "。；;":
            text += "。"
        sentences.append(text)
    return "".join(sentences)


def _ledger_result_from_judgment_fields(fields: dict, stage: str) -> str:
    """把判决/裁定抽取结果整理成人工台账偏好的管理摘要。"""
    result_text = (fields.get("处理结果") or "").strip()
    main_case_no = _display_case_no(fields.get("本案案号") or "")
    court = str(fields.get("法院名称") or "").strip()
    decision_date = _format_cn_date(fields.get("生效判决日期"))
    doc_nature = str(fields.get("文书性质") or "").strip() or _default_doc_nature(stage, main_case_no)

    prefix_bits: list[str] = []
    if court:
        prefix_bits.append(court)
    if decision_date:
        prefix_bits.append(f"于{decision_date}" if court else decision_date)

    prefix = "".join(prefix_bits)
    if prefix:
        prefix += "作出"
    if main_case_no:
        prefix += main_case_no
    if doc_nature and doc_nature not in prefix:
        prefix += doc_nature

    main_case_no_key = _case_no_key(main_case_no)
    has_management_prefix = bool(
        prefix
        and (not court or court in result_text)
        and (not main_case_no_key or main_case_no_key in _case_no_key(result_text))
    )
    if prefix and result_text and not has_management_prefix:
        result_text = f"{prefix}：{result_text}"
    elif prefix and not result_text:
        result_text = f"{prefix}：处理结果待补充"

    return _join_ledger_sentences([
        result_text,
        fields.get("后续程序"),
        fields.get("公司经济影响"),
    ])


def _traced_complete(client, *, scene: str, prompt_template_id: str,
                     messages: list, **kwargs):
    """Wrap a sync chat completion with audit tracing.

    Failure to persist the trace must never break the underlying call —
    PersistentTracer swallows persistence errors internally.
    """
    from llm_audit import get_tracer
    model = kwargs.pop("model", MODEL_CHAT)
    with get_tracer().sync_span(scene=scene) as span:
        resp = client.chat.completions.create(
            model=model, messages=messages, **kwargs,
        )
        span.record(
            model=model,
            input_messages=messages,
            output_text=resp.choices[0].message.content,
            usage=getattr(resp, "usage", None),
            prompt_template_id=prompt_template_id,
        )
    return resp


def _extract_doc_fields(client, doc: dict) -> dict:
    dtype = doc["doc_type"]
    text = doc.get("text") or ""
    if dtype in ("起诉状", "上诉状"):
        prompt = PROMPT_SUSOSTATE.replace("{text}", text[:8000])
        resp = _traced_complete(
            client,
            scene="extract_litigation_fields",
            prompt_template_id="ledger.suosostate.v1",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000, temperature=0.1,
        )
        return {"kind": "litigation", "dtype": dtype, "fields": _parse_json(resp.choices[0].message.content)}

    if dtype == "业务情况说明":
        prompt = PROMPT_BUSINESS_DESC.replace("{text}", text[:8000])
        resp = _traced_complete(
            client,
            scene="extract_business_fields",
            prompt_template_id="ledger.business_desc.v1",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800, temperature=0.1,
        )
        return {"kind": "business", "dtype": dtype, "fields": _parse_json(resp.choices[0].message.content)}

    if dtype in ("一审判决书", "二审判决书", "判决书", "裁定书", "再审申请书"):
        text_for_prompt = (text[:5000] + "\n……（中间省略）……\n" + text[-3000:]) if len(text) > 8000 else text
        prompt = PROMPT_JUDGMENT.replace("{text}", text_for_prompt)
        resp = _traced_complete(
            client,
            scene="extract_judgment_fields",
            prompt_template_id="ledger.judgment.v1",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000, temperature=0.1,
        )
        return {"kind": "judgment", "dtype": dtype, "fields": _parse_json(resp.choices[0].message.content)}

    if dtype == "强制执行申请书":
        prompt = PROMPT_EXECUTION.replace("{text}", text[:4000])
        resp = _traced_complete(
            client,
            scene="extract_execution_fields",
            prompt_template_id="ledger.execution.v1",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0.1,
        )
        return {"kind": "execution", "dtype": dtype, "fields": _parse_json(resp.choices[0].message.content)}

    return {"kind": "ignored", "dtype": dtype, "fields": {}}


def extract_case_fields(docs: list, status_fn: Callable | None = None) -> dict:
    client = get_llm_client()
    case = {
        "案件名称": "", "案件发生时间": None, "案由": "", "诉讼主体": "",
        "主诉被诉": "", "标的金额": None, "基本情况": "", "生效判决日期": None,
        "强制执行时间": None, "服务律所": None, "stages": [], "案号列表": [],
    }
    stage_order = {"一审": 1, "二审": 2, "再审": 3}
    stages_dict = {}
    litigation_claims = ""
    business_bg = ""

    docs_to_process = [
        (idx, doc)
        for idx, doc in enumerate(docs)
        if doc.get("text") and doc.get("doc_type") != "其他"
    ]

    results_by_idx: dict[int, dict] = {}
    if docs_to_process:
        max_workers = min(max(1, LEDGER_LLM_CONCURRENCY), len(docs_to_process))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for idx, doc in docs_to_process:
                if status_fn:
                    status_fn(f"🤖 AI 抽取字段 [{doc['doc_type']}]：{doc['filename']}")
                futures[executor.submit(_extract_doc_fields, client, doc)] = (idx, doc)
            for future in as_completed(futures):
                idx, doc = futures[future]
                try:
                    results_by_idx[idx] = future.result()
                except Exception as e:
                    if status_fn:
                        status_fn(f"⚠️ [{doc['doc_type']}] {doc['filename']} 字段提取失败：{e}")

    for idx in sorted(results_by_idx):
        result = results_by_idx[idx]
        kind = result["kind"]
        fields = result["fields"]

        if kind == "litigation":
            if fields.get("案号"):
                case["案号列表"].append(fields["案号"])
            for k in ["案件名称", "案件发生时间", "案由", "诉讼主体", "主诉被诉"]:
                if not case[k] and fields.get(k):
                    case[k] = fields[k]
            if case["标的金额"] is None and fields.get("标的金额") is not None:
                case["标的金额"] = fields["标的金额"]
            if not litigation_claims and fields.get("基本情况"):
                litigation_claims = fields["基本情况"]

        elif kind == "business":
            if not business_bg and fields.get("业务背景"):
                business_bg = fields["业务背景"]

        elif kind == "judgment":
            main_case_no = fields.get("本案案号") or ""
            related_case_no = fields.get("关联案号") or ""
            for no in [main_case_no, related_case_no]:
                if no:
                    case["案号列表"].append(no)
            stage = (fields.get("审级") or "").strip()
            if not stage and main_case_no:
                if "民终" in main_case_no:
                    stage = "二审"
                elif "民初" in main_case_no:
                    stage = "一审"
                elif "民申" in main_case_no:
                    stage = "再审"
            result_text = _ledger_result_from_judgment_fields(fields, stage)
            if stage:
                stages_dict[stage] = result_text or "（处理结果待补充）"
            if not case["服务律所"] and fields.get("服务律所"):
                case["服务律所"] = fields["服务律所"]
            if fields.get("生效判决日期"):
                case["生效判决日期"] = fields["生效判决日期"]

        elif kind == "execution":
            if not case["强制执行时间"] and fields.get("强制执行时间"):
                case["强制执行时间"] = fields["强制执行时间"]

    if business_bg:
        if status_fn:
            status_fn("🔀 合并业务情况说明与诉讼请求…")
        try:
            case["基本情况"] = _merge_situation_text(client, business_bg, litigation_claims)
        except Exception as e:
            if status_fn:
                status_fn(f"⚠️ 合并基本情况失败，使用原始内容：{e}")
            case["基本情况"] = "\n\n".join(filter(None, [business_bg, litigation_claims]))
    else:
        case["基本情况"] = litigation_claims

    case["stages"] = [
        {"审级": k, "处理结果": v}
        for k, v in sorted(stages_dict.items(), key=lambda x: stage_order.get(x[0], 9))
    ]
    case["案号列表"] = _dedupe_case_numbers(case["案号列表"] + _case_numbers_from_docs(docs))
    return case


# ── 台账比对与合并 ─────────────────────────────────────────────

def load_cases_json() -> list:
    p = Path(LEDGER_JSON_PATH)
    if not p.exists():
        return []
    with file_lock(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)


def save_cases_json(cases: list):
    Path(LEDGER_JSON_PATH).parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cases, ensure_ascii=False, indent=2)
    with file_lock(LEDGER_JSON_PATH):
        atomic_write_text(LEDGER_JSON_PATH, payload, encoding="utf-8")


def find_matching_case_idx(new_case: dict, existing_cases: list, docs: list = None):
    if not existing_cases:
        return None
    new_nums = {
        _case_no_key(no)
        for no in (new_case.get("案号列表", []) + _case_numbers_from_docs(docs))
        if _case_no_key(no)
    }
    if new_nums:
        for i, c in enumerate(existing_cases):
            existing_nums = {
                _case_no_key(no)
                for no in c.get("案号列表", [])
                if _case_no_key(no)
            }
            if new_nums & existing_nums:
                return i

    new_lines = []
    for k in ["案件名称", "诉讼主体", "案由"]:
        if new_case.get(k):
            new_lines.append(f"{k}：{new_case[k]}")
    if docs:
        for doc in docs:
            if doc.get("text"):
                new_lines.append(f"文书原文片段（{doc.get('doc_type','未知')}）：{doc['text'][:400]}")

    summaries = "\n".join(
        f"{i}: {c.get('案件名称','未知')} | 主体：{c.get('诉讼主体','')[:80]} | 案由：{c.get('案由','')}"
        for i, c in enumerate(existing_cases)
    )
    prompt = (
        f'你是法务专家。判断"新上传文书"是否与"现有台账"中某个案件属于同一案件。\n\n'
        f'新上传文书信息：\n' + "\n".join(new_lines) +
        f'\n\n现有台账（编号: 案件名称 | 主体 | 案由）：\n{summaries}\n\n'
        f'注意：重点比对当事人姓名/公司名称和案由是否一致。\n'
        f'如果找到匹配，只回复编号数字（如：0）。如果没有匹配，回复 -1。不要有其他内容。'
    )
    client = get_llm_client()
    response = client.chat.completions.create(
        model=MODEL_CHAT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10,
    )
    try:
        idx = int(response.choices[0].message.content.strip())
        if 0 <= idx < len(existing_cases):
            return idx
    except ValueError:
        pass
    return None


def merge_case_data(existing: dict, new_data: dict) -> dict:
    result = {**existing}
    for field in ["案件名称", "案件发生时间", "案由", "诉讼主体", "主诉被诉", "基本情况"]:
        if not result.get(field) and new_data.get(field):
            result[field] = new_data[field]
    if result.get("标的金额") is None and new_data.get("标的金额") is not None:
        result["标的金额"] = new_data["标的金额"]
    result["案号列表"] = _dedupe_case_numbers(result.get("案号列表", []) + new_data.get("案号列表", []))
    for field in ["生效判决日期", "强制执行时间", "服务律所"]:
        if new_data.get(field):
            result[field] = new_data[field]
    stage_order = {"一审": 1, "二审": 2, "再审": 3}
    existing_stage_keys = {s["审级"] for s in result.get("stages", [])}
    for stage in new_data.get("stages", []):
        if stage["审级"] not in existing_stage_keys:
            result.setdefault("stages", []).append(stage)
    result["stages"] = sorted(result.get("stages", []), key=lambda x: stage_order.get(x["审级"], 9))
    return result


_LEGAL_ALLOWED_EXTS = {".pdf", ".docx", ".doc"}
_WINDOWS_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$', re.IGNORECASE)
_LEGAL_UPLOAD_MAX_BYTES = int(os.getenv("LEGAL_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))
_LEGAL_ALLOWED_CONTENT_TYPES = {
    ".pdf": {"application/pdf", "application/octet-stream", ""},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
        "",
    },
    ".doc": {"application/msword", "application/octet-stream", ""},
}


def _safe_basename(filename: str) -> str:
    name = Path(str(filename or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("Invalid upload filename")
    return name


def _sanitize_upload_name(filename: str) -> str:
    return safe_upload_name(filename, _LEGAL_ALLOWED_EXTS)


def validate_legal_upload(filename: str, content_type: str | None, data: bytes) -> str:
    from upload_validation import validate_legal_upload as _validate_legal_upload

    return _validate_legal_upload(filename, content_type, data)

def archive_legal_docs(files_data: list, docs: list, case_name: str) -> str:
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", case_name).strip() or "未知案件"
    safe_name = safe_name[:100]
    archive_root = Path(LEGAL_ARCHIVE_ROOT).resolve()
    target_dir = (archive_root / safe_name).resolve()
    if not target_dir.is_relative_to(archive_root):
        raise ValueError(f"archive_legal_docs: case_name 越出归档根目录: {case_name!r}")
    target_dir.mkdir(parents=True, exist_ok=True)
    base = target_dir  # 已经是 resolved 路径

    for fd, doc in zip(files_data, docs):
        name = fd.get("name", "")
        data = fd.get("bytes")
        if not name or not isinstance(data, (bytes, bytearray)):
            continue

        doc_type = doc.get("doc_type", "其他")
        safe_doc_type = re.sub(r'[\\/:*?"<>|]', "_", doc_type).strip() or "其他"
        if _WINDOWS_RESERVED.match(safe_doc_type):
            safe_doc_type = f"_{safe_doc_type}"

        # 防御 1：提取纯文件名，去掉任何路径前缀
        pure_name = _sanitize_upload_name(name)

        # 防御 2：扩展名白名单（点文件特殊处理）
        if pure_name.startswith(".") and "." not in pure_name[1:]:
            ext = ".bin"          # 点文件无真实扩展名，直接归为 bin
            stem_only = pure_name  # 保留整个点文件名作为 stem（如 ".pdf"）
        else:
            ext = Path(pure_name).suffix.lower()
            stem_only = Path(pure_name).stem
            if ext not in _LEGAL_ALLOWED_EXTS:
                ext = ".bin"

        # 防御 3：清理文件名中的非法字符 + 长度限制
        safe_stem = re.sub(r'[\\/:*?"<>|]', "_", stem_only).strip() or "文件"
        safe_stem = safe_stem[:200]
        safe_filename = safe_stem + ext

        dest_name = f"{safe_doc_type}_{safe_filename}"
        dest_path = (target_dir / dest_name).resolve()

        # 越界兜底：确认路径仍在归档根目录内
        if not dest_path.is_relative_to(base):
            logging.warning("archive_legal_docs: 路径越界已跳过 %s", dest_path)
            continue

        if dest_path.exists():
            i = 2
            while i <= 9999 and (target_dir / f"{safe_doc_type}_{safe_stem}_{i}{ext}").exists():
                i += 1
            if i > 9999:
                logging.warning("archive_legal_docs: 重名文件数超限，跳过 %s", safe_filename)
                continue
            dest_path = (target_dir / f"{safe_doc_type}_{safe_stem}_{i}{ext}").resolve()

        try:
            atomic_write_bytes(dest_path, bytes(data))
        except OSError as e:
            logging.warning("archive_legal_docs: 写入失败 %s: %s", dest_path, e)
            continue

    return str(target_dir)
