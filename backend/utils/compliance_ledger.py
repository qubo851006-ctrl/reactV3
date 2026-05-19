import json
import re
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from config import (
    COMPLIANCE_LEDGER_DIR,
    COMPLIANCE_LEDGER_EXCEL_PATH,
    COMPLIANCE_LEDGER_JSON_PATH,
    COMPLIANCE_RESPONSIBLE_PERSONS_PATH,
)
from file_store import atomic_write_text, file_lock


COMPLIANCE_EXTRACT_MODEL = "qwen2.5-72b"
COMPLIANCE_REVIEW_MODEL = "DeepSeek-V3"
CHIEF_COMPLIANCE_PERSON = "胡鹏斌"
COMPLIANCE_DEBUG_PATH = Path(COMPLIANCE_LEDGER_DIR) / "debug-last.json"

DEFAULT_RESPONSIBLE_PERSONS = {
    "规划与资产部/深化改革领导小组办公室": "富小鹏",
    "财务部": "杨焕",
    "审计部/法务合规部": "李莹",
    "人力资源部": "陈锐",
    "党群办公室/董事会办公室/行政办公室": "刘芳",
    "安全质量部": "霍晓冬",
    "纪委办公室/巡察工作领导小组办公室": "边宁",
    "西南分公司（四川中航物业）": "张虎",
}

VALID_IMPLEMENTATIONS = {"已按要求补充完善", "未见落实", "不涉及", "/"}
WORKSHEET_NAME = "合规管理牵头部门合规审查台账"
HEADERS = ["序号", "重大事项", "程序", "审查时间", "审查单位", "合规审查意见", "具体意见描述", "落实情况", "承办单位", "背景材料"]


def load_responsible_persons(path: str | Path = COMPLIANCE_RESPONSIBLE_PERSONS_PATH) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return dict(DEFAULT_RESPONSIBLE_PERSONS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_RESPONSIBLE_PERSONS)
    if not isinstance(data, dict):
        return dict(DEFAULT_RESPONSIBLE_PERSONS)
    result = dict(DEFAULT_RESPONSIBLE_PERSONS)
    for dept, person in data.items():
        dept_text = str(dept).strip()
        person_text = str(person).strip()
        if dept_text and person_text:
            result[dept_text] = person_text
    return result


def save_responsible_persons(persons: dict[str, str], path: str | Path = COMPLIANCE_RESPONSIBLE_PERSONS_PATH) -> dict[str, str]:
    cleaned = {}
    for dept, person in persons.items():
        dept_text = str(dept).strip()
        person_text = str(person).strip()
        if dept_text and person_text:
            cleaned[dept_text] = person_text
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(p):
        atomic_write_text(p, json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    return cleaned


def normalize_review_opinion(opinion_text: str | None) -> str:
    text = re.sub(r"\s+", "", opinion_text or "")
    if any(word in text for word in ["不同意", "不予同意", "暂不同意"]):
        return "不予同意"
    if ("同意" in text or "拟同意" in text) and re.search(r"建议(提交|提请|报|上报).{0,20}(会议|审议)", text):
        return "同意"
    supplement_patterns = [
        "建议补充",
        "建议完善",
        "补充完善",
        "修改完善",
        "补充材料",
        "补充依据",
        "请补充",
        "需补充",
        "请进一步完善",
        "需进一步完善",
        "建议调整",
        "建议修改",
    ]
    if any(word in text for word in supplement_patterns):
        return "建议补充完善"
    return "同意"


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _normalize_implementation(value: Any, opinion_text: str) -> str:
    text = _clean_text(value, "")
    if text in VALID_IMPLEMENTATIONS:
        return text
    if normalize_review_opinion(opinion_text) == "建议补充完善":
        return "未见落实"
    return "/"


def _detail_for_opinion(item: dict[str, Any]) -> str:
    detail = _clean_text(item.get("detail"), "")
    if detail:
        return detail
    opinion_text = _clean_text(item.get("opinion_text"), "")
    if normalize_review_opinion(opinion_text) == "同意":
        if len(opinion_text) > 20:
            return opinion_text
        return "/"
    return opinion_text or "/"


def _row_from(role: str, item: dict[str, Any], department: str | None = None) -> dict[str, str]:
    dept = _clean_text(department if department is not None else item.get("department"), "")
    if role == "首席合规官":
        review_unit = "首席合规官"
    else:
        review_unit = f"{role}（{dept}）" if dept else role
    opinion_text = _clean_text(item.get("opinion_text"), "")
    return {
        "review_time": _clean_text(item.get("time"), ""),
        "review_unit": review_unit,
        "review_opinion": normalize_review_opinion(opinion_text),
        "detail": _detail_for_opinion(item),
        "implementation": _normalize_implementation(item.get("implementation"), opinion_text),
    }


def _normalize_person_name(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _approval_entry_to_item(entry: dict[str, Any]) -> dict[str, str]:
    return {
        "department": _clean_text(entry.get("department"), ""),
        "person": _clean_text(entry.get("person") or entry.get("signer"), ""),
        "time": _clean_text(entry.get("time") or entry.get("signed_at"), ""),
        "opinion_text": _clean_text(entry.get("opinion_text") or entry.get("opinion"), ""),
        "detail": _clean_text(entry.get("detail"), ""),
        "implementation": _clean_text(entry.get("implementation"), "/"),
    }


def _is_compliance_department(department: str, person: str, persons: dict[str, str]) -> bool:
    configured = _normalize_person_name(persons.get("审计部/法务合规部"))
    return bool(configured and _normalize_person_name(person) == configured)


def _configured_department_for_person(department: str, person: str, persons: dict[str, str]) -> str | None:
    dept_key = re.sub(r"\s+", "", department)
    person_key = _normalize_person_name(person)
    for configured_dept, configured_person in persons.items():
        normalized_dept = re.sub(r"\s+", "", configured_dept)
        normalized_person = _normalize_person_name(configured_person)
        if not normalized_person or person_key != normalized_person:
            continue
        if normalized_dept == "审计部/法务合规部":
            return None
        if normalized_dept == dept_key or normalized_dept in dept_key or dept_key in normalized_dept:
            return configured_dept
    return None


def _is_countersign_section(entry: dict[str, Any]) -> bool:
    section = str(
        entry.get("source_section")
        or entry.get("section")
        or entry.get("source")
        or ""
    )
    return "会签" in section


_SIGN_TIME_RE = re.compile(r"20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?")


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"[\s　]+", "", str(value or ""))


def _extract_countersign_section(text: str) -> str:
    match = re.search(r"会签", text or "")
    if not match:
        return ""
    section = text[match.end():]
    stops = [
        "批准部门意见",
        "拟稿单位意见",
        "办公室主任审核",
        "拟稿单位负责人",
        "承办单位意见",
    ]
    stop_positions = [section.find(marker) for marker in stops if section.find(marker) >= 0]
    if stop_positions:
        section = section[:min(stop_positions)]
    return section


def _opinion_before_signer(section: str, signer_start: int) -> str:
    prefix = section[:signer_start]
    last_time = None
    for match in _SIGN_TIME_RE.finditer(prefix):
        last_time = match
    if last_time:
        prefix = prefix[last_time.end():]
    lines = [line.strip() for line in prefix.splitlines() if line.strip()]
    if not lines:
        return "已阅。"
    opinion_lines: list[str] = []
    for line in reversed(lines):
        if _SIGN_TIME_RE.search(line):
            break
        opinion_lines.insert(0, line)
        if len(opinion_lines) >= 3:
            break
    opinion = "\n".join(opinion_lines).strip()
    return opinion or "已阅。"


def _find_person_match(section: str, person: str) -> re.Match[str] | None:
    compact_person = _normalize_match_text(person)
    if not compact_person:
        return None
    pattern = r"[\s　]*".join(re.escape(char) for char in compact_person)
    return re.search(pattern, section)


def _time_near_signer(section: str, signer_match: re.Match[str]) -> str:
    after = section[signer_match.end():signer_match.end() + 100]
    after_match = _SIGN_TIME_RE.search(after)
    if after_match:
        return after_match.group(0)
    before = section[max(0, signer_match.start() - 100):signer_match.start()]
    before_matches = list(_SIGN_TIME_RE.finditer(before))
    return before_matches[-1].group(0) if before_matches else ""


def _trim_opinion_segment(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    text = re.sub(r"(?:中航建设直属|直属|部门|单位)\s*$", "", text).strip()
    sentence_match = re.search(r"([^。！？；;]*[。！？；;])\s*(?:中航建设直属|直属)?\s*$", text)
    if sentence_match:
        return sentence_match.group(1).strip()
    return text


def _last_independent_opinion(value: str) -> str:
    text = re.sub(r"\s+", "", value or "")
    if not text:
        return ""
    sentences = re.findall(r"[^。！？；;]+[。！？；;]?", text)
    sentences = [s for s in sentences if s]
    if len(sentences) <= 1:
        return text
    return sentences[-1]


def _opinion_before_signer_match(text: str, signer_match: re.Match[str]) -> str:
    prefix = text[:signer_match.start()]
    time_matches = list(_SIGN_TIME_RE.finditer(prefix))
    if time_matches:
        prefix = prefix[time_matches[-1].end():]
    else:
        section_match = re.search(r"签发意见|签批意见", prefix)
        if section_match:
            prefix = prefix[section_match.end():]
    return _trim_opinion_segment(prefix)


def _is_ambiguous_chief_source(text: str, signer_match: re.Match[str]) -> bool:
    line_start = text.rfind("\n", 0, signer_match.start())
    line_end = text.find("\n", signer_match.end())
    if line_start < 0:
        line_start = max(0, signer_match.start() - 300)
    if line_end < 0:
        line_end = min(len(text), signer_match.end() + 300)
    window = text[line_start:line_end]
    return len(_SIGN_TIME_RE.findall(window)) >= 2


def _supplement_countersign_from_text(raw: dict[str, Any], text: str, persons: dict[str, str]) -> dict[str, Any]:
    section = _extract_countersign_section(text)
    if not section:
        return raw

    next_raw = dict(raw)
    countersign = [
        dict(entry)
        for entry in (next_raw.get("countersign") or [])
        if isinstance(entry, dict)
    ]
    existing_departments = {
        re.sub(r"\s+", "", configured)
        for entry in countersign
        if (
            configured := _configured_department_for_person(
                _clean_text(entry.get("department"), ""),
                _clean_text(entry.get("person") or entry.get("signer"), ""),
                persons,
            )
        )
    }
    normalized_section = _normalize_match_text(section)

    for department, person in persons.items():
        configured_dept = _configured_department_for_person(department, person, persons)
        if not configured_dept:
            continue
        dept_key = re.sub(r"\s+", "", configured_dept)
        if dept_key in existing_departments:
            continue

        person_key = _normalize_match_text(person)
        dept_match_key = _normalize_match_text(configured_dept)
        person_pos = normalized_section.find(person_key)
        if person_pos < 0 or dept_match_key not in normalized_section[max(0, person_pos - 300):person_pos + 300]:
            continue

        signer_match = _find_person_match(section, str(person))
        if not signer_match:
            continue
        countersign.append({
            "department": configured_dept,
            "person": str(person),
            "time": _time_near_signer(section, signer_match),
            "opinion_text": _opinion_before_signer(section, signer_match.start()),
            "detail": "",
            "implementation": "/",
        })
        existing_departments.add(dept_key)

    if countersign:
        next_raw["countersign"] = countersign
    return next_raw


def _deduplicate_chief_opinion(chief: dict[str, Any], entries: list) -> dict[str, Any]:
    opinion = _clean_text(chief.get("opinion_text"), "")
    if not opinion or len(opinion) < 10:
        return chief
    chief_person = _normalize_person_name(chief.get("person", ""))
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_person = _normalize_person_name(
            entry.get("person") or entry.get("signer") or ""
        )
        if not entry_person or entry_person == chief_person:
            continue
        entry_opinion = _clean_text(
            entry.get("opinion_text") or entry.get("opinion"), ""
        )
        if entry_opinion and len(entry_opinion) > 3 and entry_opinion in opinion and entry_opinion != opinion:
            opinion = opinion.replace(entry_opinion, "").strip()
            opinion = re.sub(r"^[。，、；\s]+", "", opinion)
    if opinion != _clean_text(chief.get("opinion_text"), ""):
        result = dict(chief)
        result["opinion_text"] = opinion
        return result
    return chief


def _find_signer_with_timestamp(text: str, person: str) -> re.Match[str] | None:
    compact = _normalize_match_text(person)
    if not compact:
        return None
    pattern = r"[\s　]*".join(re.escape(c) for c in compact)
    best = None
    for m in re.finditer(pattern, text):
        after = text[m.end():m.end() + 100]
        if _SIGN_TIME_RE.search(after):
            best = m
    return best


def _fix_chief_opinion_from_text(raw: dict[str, Any], text: str) -> dict[str, Any]:
    chief = raw.get("chief")
    if not chief or not isinstance(chief, dict) or not text:
        return raw
    signer_match = _find_signer_with_timestamp(text, CHIEF_COMPLIANCE_PERSON)
    if not signer_match:
        return raw
    extracted_opinion = _opinion_before_signer_match(text, signer_match)
    time = _time_near_signer(text, signer_match)
    current_opinion = _clean_text(chief.get("opinion_text"), "")
    current_tail = _last_independent_opinion(current_opinion)
    ambiguous_source = _is_ambiguous_chief_source(text, signer_match)
    if (not extracted_opinion or extracted_opinion == "已阅。") and ambiguous_source and current_tail != current_opinion:
        extracted_opinion = current_tail
    if not extracted_opinion or extracted_opinion == "已阅。":
        return raw
    if (
        current_tail
        and current_tail != current_opinion
        and (
            current_tail in extracted_opinion
            or ambiguous_source
        )
    ):
        extracted_opinion = current_tail
    normalized_extracted = re.sub(r"\s+", "", extracted_opinion)
    normalized_current = re.sub(r"\s+", "", current_opinion)
    detail = _clean_text(chief.get("detail"), "")
    normalized_detail = re.sub(r"\s+", "", detail)
    if normalized_extracted == normalized_current and (not detail or normalized_detail == normalized_extracted):
        return raw
    next_raw = dict(raw)
    next_chief = dict(chief)
    next_chief["person"] = CHIEF_COMPLIANCE_PERSON
    next_chief["opinion_text"] = extracted_opinion
    next_chief["detail"] = ""
    if time:
        next_chief["time"] = time
    next_raw["chief"] = next_chief
    return next_raw


def _chief_text_window(text: str) -> str:
    signer_match = _find_signer_with_timestamp(text, CHIEF_COMPLIANCE_PERSON)
    if not signer_match:
        compact_name = _normalize_match_text(CHIEF_COMPLIANCE_PERSON)
        pos = _normalize_match_text(text).find(compact_name)
        return text[:1200] if pos < 0 else text[max(0, pos - 500):pos + 700]
    return text[max(0, signer_match.start() - 700):signer_match.end() + 500]


def _write_compliance_debug(payload: dict[str, Any]) -> None:
    try:
        COMPLIANCE_DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            COMPLIANCE_DEBUG_PATH,
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _apply_approval_entries(raw: dict[str, Any], persons: dict[str, str]) -> dict[str, Any]:
    entries = raw.get("approval_entries") or raw.get("approvals") or []
    if not isinstance(entries, list):
        return raw

    next_raw = dict(raw)
    countersign_by_department = {
        re.sub(r"\s+", "", str(entry.get("department") or "")): entry
        for entry in (next_raw.get("countersign") or [])
        if isinstance(entry, dict)
    }
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item = _approval_entry_to_item(entry)
        person = item.get("person", "")
        department = item.get("department", "")
        if _normalize_person_name(person) == CHIEF_COMPLIANCE_PERSON:
            next_raw["chief"] = item
        elif _is_compliance_department(department, person, persons):
            next_raw["compliance"] = item
        else:
            configured_dept = _configured_department_for_person(department, person, persons)
            if configured_dept:
                dept_key = re.sub(r"\s+", "", configured_dept)
                countersign_item = dict(item)
                countersign_item["department"] = configured_dept
                countersign_by_department[dept_key] = countersign_item

    chief = next_raw.get("chief")
    if chief and isinstance(chief, dict):
        next_raw["chief"] = _deduplicate_chief_opinion(chief, entries)

    if countersign_by_department:
        next_raw["countersign"] = list(countersign_by_department.values())

    return next_raw


def _filtered_countersign_entries(countersign: Any, persons: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(countersign, list):
        return []
    filtered: dict[str, dict[str, Any]] = {}
    for entry in countersign:
        if not isinstance(entry, dict):
            continue
        configured_dept = _configured_department_for_person(
            _clean_text(entry.get("department"), ""),
            _clean_text(entry.get("person") or entry.get("signer"), ""),
            persons,
        )
        if configured_dept:
            next_entry = dict(entry)
            next_entry["department"] = configured_dept
            filtered[re.sub(r"\s+", "", configured_dept)] = next_entry
    return list(filtered.values())


def build_review_rows(item: dict[str, Any], responsible_persons: dict[str, str] | None = None) -> list[dict[str, str]]:
    persons = responsible_persons or load_responsible_persons()
    rows: list[dict[str, str]] = []
    chief = item.get("chief") or {}
    compliance = item.get("compliance") or {}
    countersign = _filtered_countersign_entries(item.get("countersign") or [], persons)
    undertaking = item.get("undertaking") or {}

    if chief:
        rows.append(_row_from("首席合规官", chief))
    if compliance:
        rows.append(_row_from("合规管理牵头部门", compliance, compliance.get("department") or "审计部/法务合规部"))
    for entry in countersign:
        if isinstance(entry, dict):
            rows.append(_row_from("会签单位", entry))
    if undertaking:
        rows.append(_row_from("承办单位", undertaking))

    return rows or [_row_from("承办单位", {})]


def _normalize_procedure(value: Any) -> str:
    text = _clean_text(value, "")
    if "董事" in text:
        return "董事会审议"
    return "总办会审议"


def normalize_extracted_item(raw: dict[str, Any], responsible_persons: dict[str, str] | None = None) -> dict[str, Any]:
    if raw.get("approval_entries") or raw.get("approvals"):
        raw = _apply_approval_entries(raw, responsible_persons or load_responsible_persons())
    background = raw.get("background_materials") or raw.get("attachments") or []
    if isinstance(background, str):
        background_items = [background]
    else:
        background_items = [str(x).strip() for x in background if str(x).strip()]
    return {
        "title": _clean_text(raw.get("title") or raw.get("重大事项"), "未识别标题"),
        "procedure": _normalize_procedure(raw.get("procedure") or raw.get("程序")),
        "undertaking_department": "法务合规部",
        "background_materials": [re.sub(r"\.(pdf|docx?|xlsx?|xls)$", "", x, flags=re.IGNORECASE) for x in background_items],
        "review_rows": raw.get("review_rows") or build_review_rows(raw, responsible_persons),
        "warnings": raw.get("warnings") or [],
    }


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM 未返回 JSON 对象")
    return json.loads(match.group())


def _needs_ocr(text: str) -> bool:
    if not text.strip():
        return True
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    slash_tokens = len(re.findall(r"/\d+", text))
    return chinese_count < 20 or slash_tokens > chinese_count


def extract_pdf_text(pdf_bytes: bytes, filename: str, vision_model: str | None = None) -> str:
    from ledger_helpers import extract_file_text, ocr_pdf_with_vision

    text = extract_file_text(pdf_bytes, filename)
    if _needs_ocr(text):
        text = ocr_pdf_with_vision(pdf_bytes, model=vision_model)
    return text


def _build_extract_prompt(text: str, persons: dict[str, str]) -> str:
    return f"""你是企业合规审查台账录入助手。请从 OA 流程表单/审批记录中提取合规审查工作台账字段。

部门负责人配置：
{json.dumps(persons, ensure_ascii=False, indent=2)}

抽取规则：
1. title 填文件信息中的标题内容。
2. procedure 只能填“董事会审议”或“总办会审议”，根据正文判断。
3. undertaking 取“拟稿单位意见”中对应部门负责人的意见。
4. countersign 取会签意见中除“审计部/法务合规部”以外的部门负责人意见；多个部门逐个返回。
5. compliance 取会签意见中的“审计部/法务合规部”负责人意见。
6. chief 只能取签署人为”胡鹏斌”的那一条意见；不得合并其他领导、其他部门、相邻行的意见。
7. approval_entries 逐条列出 OA 中每条独立审批意见，每条必须包含 department、person、time、opinion_text；不得把两个签署人的意见合并成一条。
12. OA 签发/签批区格式：每条意见的结构是”意见正文”在上、”部门 签署人 时间”在下。每段意见文字只属于其正下方紧邻的签署人，不属于上方或更远的签署人。签发区有多位签署人时，每人只取紧挨其上方的那一段意见，严禁将相邻签署人的意见合并。
8. 每个意见对象包含 department、person、time、opinion_text、detail、implementation。
9. “拟同意，建议提交/提请……会议审议”属于同意类意见，不属于“建议补充完善”。
10. implementation 只能填“/”“已按要求补充完善”“未见落实”“不涉及”。
11. attachments 提取正文附件列表中的附件名称，去掉 PDF/DOC/XLS 等后缀。

只返回 JSON 对象，格式如下：
{{
  "title": "",
  "procedure": "董事会审议",
  "attachments": [],
  "undertaking": {{"department": "", "person": "", "time": "", "opinion_text": "", "detail": "", "implementation": "/"}},
  "approval_entries": [],
  "countersign": [],
  "compliance": {{"department": "审计部/法务合规部", "person": "", "time": "", "opinion_text": "", "detail": "", "implementation": "/"}},
  "chief": {{"person": "胡鹏斌", "time": "", "opinion_text": "", "detail": "", "implementation": "/"}},
  "warnings": []
}}

PDF/OA内容：
{text[:16000]}"""


def _build_review_prompt(text: str, persons: dict[str, str], extracted: dict[str, Any]) -> str:
    return f"""你是企业合规审查台账复核助手。请基于同一份 OA 流程表单/审批记录，对模型 A 已提取的合规审查台账 JSON 逐项校验。

要求：
1. 重点校验重大事项标题、董事会/总办会程序、承办单位意见、会签单位意见、合规管理牵头部门意见、首席合规官意见、签署时间、背景材料。
2. 如模型 A 漏提或错提，请直接修正为最终可写入台账的 JSON。
3. 返回格式必须与模型 A JSON 完全一致，只返回 JSON 对象，不要解释文字。
4. 每条审批意见必须按签署人独立校验，首席合规官只能取胡鹏斌本人意见，不得混入其他领导意见。签发/签批区每段意见文字只属于其正下方紧邻的签署人。
5. “拟同意，建议提交/提请……会议审议”应视为同意类意见，不应改成建议补充完善。
6. 不确定但不影响填表的内容，可在 warnings 中追加提示。

部门负责人配置：
{json.dumps(persons, ensure_ascii=False, indent=2)}

模型 A 提取结果：
{json.dumps(extracted, ensure_ascii=False, indent=2)}

PDF/OA内容：
{text[:16000]}"""


def _append_warning(item: dict[str, Any], warning: str) -> dict[str, Any]:
    next_item = dict(item)
    warnings = list(next_item.get("warnings") or [])
    warnings.append(warning)
    next_item["warnings"] = warnings
    return next_item


def extract_compliance_item(text: str, responsible_persons: dict[str, str] | None = None) -> dict[str, Any]:
    from llm_client import get_llm_client
    from llm_audit import traced_complete

    persons = responsible_persons or load_responsible_persons()
    client = get_llm_client()

    # Compliance is a multi-step pipeline (extract → review → fix → normalize).
    # inject_few_shot=False here on purpose: the few-shot examples we'd
    # inject are normalized review_rows output (post-build_review_rows),
    # which is structurally different from the 5-tuple schema this prompt
    # asks for (undertaking / compliance / chief / approval_entries /
    # countersign). When the example shape doesn't match the prompt's
    # requested shape, the LLM tries to bridge the two and drops fields
    # (observed in production 2026-05-19: chief / compliance / undertaking
    # rows all silently disappeared from the final ledger, only countersign
    # entries survived). Few-shot is appropriate for SINGLE-step extraction
    # where the user's edited_to is the same schema as the prompt asks for —
    # not for multi-step pipelines like this one.
    extract_response = traced_complete(
        client,
        scene="compliance_extract",
        prompt_template_id="compliance.extract.v1",
        model=COMPLIANCE_EXTRACT_MODEL,
        messages=[{"role": "user", "content": _build_extract_prompt(text, persons)}],
        temperature=0,
        max_tokens=3000,
        inject_few_shot=False,
    )
    extract_raw = extract_response.choices[0].message.content or ""
    extracted = _parse_json_object(extract_raw)

    try:
        review_response = traced_complete(
            client,
            scene="compliance_review",
            prompt_template_id="compliance.review.v1",
            model=COMPLIANCE_REVIEW_MODEL,
            messages=[{"role": "user", "content": _build_review_prompt(text, persons, extracted)}],
            temperature=0,
            max_tokens=3000,
            inject_few_shot=False,
        )
        reviewed = _parse_json_object(review_response.choices[0].message.content or "")
    except Exception as exc:
        reviewed = _append_warning(extracted, f"DeepSeek 校验失败，已保留 Qwen 提取结果：{exc}")

    reviewed_before_fix = reviewed
    reviewed_after_countersign = _supplement_countersign_from_text(reviewed_before_fix, text, persons)
    reviewed_after_chief = _fix_chief_opinion_from_text(reviewed_after_countersign, text)
    reviewed_for_rows = dict(reviewed_after_chief)
    reviewed_for_rows.pop("review_rows", None)
    final_item = normalize_extracted_item(reviewed_for_rows, persons)
    _write_compliance_debug({
        "debug_version": "compliance-chief-diagnosis-v1",
        "text_length": len(text or ""),
        "chief_text_window": _chief_text_window(text or ""),
        "qwen_extracted_chief": extracted.get("chief") if isinstance(extracted, dict) else None,
        "qwen_extracted_review_rows": extracted.get("review_rows") if isinstance(extracted, dict) else None,
        "reviewed_chief_before_fix": reviewed_before_fix.get("chief") if isinstance(reviewed_before_fix, dict) else None,
        "reviewed_review_rows_before_fix": reviewed_before_fix.get("review_rows") if isinstance(reviewed_before_fix, dict) else None,
        "chief_after_fix": reviewed_after_chief.get("chief") if isinstance(reviewed_after_chief, dict) else None,
        "final_review_rows": final_item.get("review_rows"),
    })
    return final_item


# -- Persistence surface re-exported from compliance_persistence ---
# Moved out of this module to keep extraction + review logic separate
# from JSON/Excel I/O. Importers keep working unchanged.
from utils.compliance_persistence import (  # noqa: E402
    HEADERS,
    WORKSHEET_NAME,
    append_record,
    create_compliance_workbook,
    load_records,
    save_records,
    upsert_record,
    _normalize_record_key,
)
