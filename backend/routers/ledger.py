import asyncio
import os
import json
import secrets
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from auth_utils import get_current_user, require_admin
from audit_log import write_log
from db import get_db
from models import User
from file_store import atomic_write_bytes, atomic_write_text, file_lock, safe_child_path

from config import LEDGER_JSON_PATH, LEDGER_EXCEL_PATH, LEDGER_OUTPUT_DIR
from ledger_helpers import (
    LEDGER_DOC_CONCURRENCY,
    extract_file_text, ocr_pdf_with_vision, needs_ocr_text,
    detect_doc_type_by_content,
    extract_case_fields, load_cases_json, save_cases_json,
    find_matching_case_idx, merge_case_data, archive_legal_docs,
    validate_legal_upload,
)
from perf_trace import PerfTrace
from routers.chat import load_history, save_history

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

_PENDING_UPLOAD_ROOT = Path(LEDGER_OUTPUT_DIR) / "_pending_uploads"
_PENDING_ID_PREFIX = "pending_"


def _pending_user_dir(user_id: int) -> Path:
    return _PENDING_UPLOAD_ROOT / f"user_{user_id}"


def _pending_dir_for(user_id: int, pending_id: str) -> Path:
    if not pending_id.startswith(_PENDING_ID_PREFIX) or not pending_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("无效的待归档编号")
    return safe_child_path(_pending_user_dir(user_id), pending_id)


def _create_pending_upload(user_id: int, files_data: list[dict], docs: list[dict]) -> str:
    pending_id = f"{_PENDING_ID_PREFIX}{secrets.token_urlsafe(12)}"
    pending_dir = _pending_dir_for(user_id, pending_id)
    pending_dir.mkdir(parents=True, exist_ok=False)
    meta_items = []
    for idx, (fd, doc) in enumerate(zip(files_data, docs)):
        ext = Path(fd.get("name", "")).suffix.lower() or ".bin"
        stored_name = f"{idx}{ext}"
        atomic_write_bytes(pending_dir / stored_name, bytes(fd.get("bytes") or b""))
        meta_items.append({
            "stored_name": stored_name,
            "name": fd.get("name", ""),
            "doc_type": doc.get("doc_type", "其他"),
        })
    atomic_write_text(pending_dir / "meta.json", json.dumps(meta_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return pending_id


def _commit_pending_archive(user_id: int, pending_id: str, case_name: str) -> str:
    pending_dir = _pending_dir_for(user_id, pending_id)
    meta_path = pending_dir / "meta.json"
    if not meta_path.exists():
        raise ValueError("待归档文件不存在或已过期")
    meta_items = json.loads(meta_path.read_text(encoding="utf-8"))
    files_data = []
    docs = []
    for item in meta_items:
        stored_path = safe_child_path(pending_dir, item.get("stored_name", ""))
        files_data.append({"name": item.get("name", ""), "bytes": stored_path.read_bytes()})
        docs.append({"doc_type": item.get("doc_type", "其他")})
    archive_dir = archive_legal_docs(files_data, docs, case_name)
    shutil.rmtree(pending_dir, ignore_errors=True)
    return archive_dir


def _process_ledger_file(fd: dict, vision_model: str) -> dict:
    text = extract_file_text(fd["bytes"], fd["name"])
    is_pdf = os.path.splitext(fd["name"])[1].lower() == ".pdf"
    used_ocr = False
    if is_pdf and needs_ocr_text(text):
        text = ocr_pdf_with_vision(fd["bytes"], model=vision_model)
        used_ocr = True
    doc_type = detect_doc_type_by_content(text) if text else "其他"
    return {
        "filename": fd["name"],
        "text": text,
        "doc_type": doc_type,
        "used_ocr": used_ocr,
    }


def _extract_ledger_docs(files_data: list[dict], vision_model: str, status_fn=None) -> list[dict]:
    docs: list[dict | None] = [None] * len(files_data)
    max_workers = min(max(1, LEDGER_DOC_CONCURRENCY), len(files_data) or 1)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_ledger_file, fd, vision_model): (idx, fd)
            for idx, fd in enumerate(files_data)
        }
        for future in as_completed(futures):
            idx, fd = futures[future]
            doc = future.result()
            docs[idx] = doc
            if status_fn:
                ocr_text = "，已触发 OCR" if doc.get("used_ocr") else ""
                status_fn(
                    f"→ `{fd['name']}` 提取到 **{len(doc.get('text') or '')}** 字符，"
                    f"文书类型：**{doc.get('doc_type') or '其他'}**{ocr_text}"
                )
    return [doc for doc in docs if doc is not None]


# ── 提取（SSE 流式，不写入）──────────────────────────────────

@router.post("/extract")
async def extract_ledger(
    files: list[UploadFile] = File(...),
    vision_model: str = Form(""),
    user: User = Depends(get_current_user),
):
    """
    流式提取案件信息、比对台账、归档文书，但不写入 cases.json / Excel。
    SSE 最终事件携带 preview 数据供前端展示确认。
    """
    # 提前捕获 user.id，避免在 SSE 生成器内访问已关闭的数据库会话
    user_id = user.id
    files_data = []
    for f in files:
        b = await f.read()
        try:
            safe_name = validate_legal_upload(f.filename or "", f.content_type, b)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        files_data.append({"name": safe_name, "bytes": b, "content_type": f.content_type})

    async def event_stream() -> AsyncGenerator[str, None]:
        from llm_audit.context import collect_traces
        overall_start = time.perf_counter()
        trace = PerfTrace("ledger.extract", user_id)

        def used_since(start: float) -> str:
            return f"{time.perf_counter() - start:.1f}s"

        def send(msg: str) -> str:
            return f"data: {json.dumps({'log': msg}, ensure_ascii=False)}\n\n"

        def send_error(msg: str) -> str:
            return f"data: {json.dumps({'error': msg}, ensure_ascii=False)}\n\n"

        # Collect every trace_id produced by LLM calls in this extract turn.
        # Returned in preview_payload so the frontend can attach user
        # accept/edit feedback after confirming.
        with collect_traces() as trace_bucket:
            # Step 1: 并发提取文字 / OCR / 文书类型
            yield send(f"**Step 1** 📄 并发提取文字与识别文书类型（{len(files_data)} 个文件）…")
            doc_status: list[str] = []
            text_start = time.perf_counter()
            with trace.step("extract_docs"):
                docs = await asyncio.to_thread(
                    _extract_ledger_docs,
                    files_data,
                    vision_model,
                    doc_status.append,
                )
            for msg in doc_status:
                yield send(msg)
            yield send(f"→ 文件处理完成，用时 {used_since(text_start)}")

            if not any((doc.get("text") or "").strip() for doc in docs):
                yield send_error("OCR 未识别到可用于案件台账生成的正文，请检查扫描件清晰度或 OCR 服务配置后重试。")
                trace.finish()
                return

            # Step 2: AI 提取字段（阻塞 LLM 调用卸载到线程池）
            yield send("**Step 2** 🤖 AI 抽取案件字段…")
            fields_start = time.perf_counter()
            with trace.step("extract_case_fields"):
                new_case = await asyncio.to_thread(extract_case_fields, docs, lambda m: None)
            yield send(f"→ AI 字段提取完成，用时 {used_since(fields_start)}")
            yield send(f"→ 案件名称：**{new_case.get('案件名称') or '（未提取到）'}**")
            yield send(f"→ 案由：**{new_case.get('案由') or '（未提取到）'}**")
            yield send(f"→ 标的金额：**{new_case.get('标的金额') or '（未提取到）'}**")

            # Step 3: 比对台账（可能含 LLM 调用，卸载到线程池）
            yield send("**Step 3** 🔍 比对现有台账…")
            match_start = time.perf_counter()
            with trace.step("match_existing_ledger"):
                existing_cases = await asyncio.to_thread(load_cases_json)
                match_idx = await asyncio.to_thread(find_matching_case_idx, new_case, existing_cases, docs)
            yield send(f"→ 台账匹配完成，用时 {used_since(match_start)}")
            yield send(f"→ {'匹配到第 ' + str(match_idx + 1) + ' 条记录' if match_idx is not None else '未匹配，将新增'}")

            # Step 4: 准备预览数据（合并但不保存）
            existing_archive_name = ""  # 已有案件的归档目录名，用于保证同案件文书归入同一文件夹
            if match_idx is not None:
                existing_archive_name = existing_cases[match_idx].get("案件名称", "")
                preview_case = merge_case_data(existing_cases[match_idx], new_case)
                case_name = preview_case.get("案件名称", "")
                stage_summary = "、".join(s["审级"] for s in preview_case.get("stages", []))
                action_text = f"已有案件「{case_name}」，将更新（审级：{stage_summary or '无'}）"
                is_new = False
            else:
                preview_case = new_case
                case_name = preview_case.get("案件名称", "")
                action_text = f"新案件「{case_name or '（待补充）'}」，将新增至台账"
                is_new = True

            # Step 5: 暂存待归档文书，确认写入后再进入正式归档目录。
            yield send("📁 暂存待归档文书…")
            archive_start = time.perf_counter()
            with trace.step("stage_pending_archive"):
                pending_archive_id = await asyncio.to_thread(_create_pending_upload, user_id, files_data, docs)
            yield send(f"→ 已暂存，用时 {used_since(archive_start)}")

            yield send(f"✅ 提取完成，总用时 {used_since(overall_start)}，等待确认…")
            trace.finish()

        preview_payload = {
            "preview": True,
            "case_data": preview_case,
            "match_idx": match_idx,
            "is_new": is_new,
            "action_text": action_text,
            "archive_dir": "",
            "existing_archive_name": existing_archive_name,
            "pending_archive_id": pending_archive_id,
            "existing_count": len(existing_cases),
            "llm_trace_ids": list(trace_bucket.ids),
        }
        yield f"data: {json.dumps(preview_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── 确认写入台账 ──────────────────────────────────────────────

class LedgerWriteRequest(BaseModel):
    case_data: dict
    match_idx: int | None
    archive_dir: str
    existing_archive_name: str = ""
    pending_archive_id: str = ""
    session_id: str = ""


@router.post("/write")
def write_ledger_confirm(
    req: LedgerWriteRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    用户确认后将案件数据写入 cases.json 和 Excel。
    """
    output_dir = Path(LEDGER_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        # 匹配到已有案件时，使用已有案件名称作为归档目录名，保证同案件文书归入同一文件夹
        archive_case_name = req.existing_archive_name or req.case_data.get("案件名称", "")
        archive_dir = _commit_pending_archive(user.id, req.pending_archive_id, archive_case_name) if req.pending_archive_id else req.archive_dir
    except Exception as e:
        write_log(db, user, "ledger_archive_failed", f"案件文书归档失败：{e}", request)
        raise HTTPException(status_code=500, detail=f"文书归档失败：{e}")

    txn_lock = Path(LEDGER_JSON_PATH).with_suffix(".txn")
    with file_lock(txn_lock):
        existing_cases = load_cases_json()
        updated_cases = list(existing_cases)

        if req.match_idx is not None and 0 <= req.match_idx < len(updated_cases):
            updated_cases[req.match_idx] = req.case_data
            action_text = f"已更新案件「{req.case_data.get('案件名称', '')}」"
            is_new = False
        else:
            updated_cases.append(req.case_data)
            action_text = f"已新增案件「{req.case_data.get('案件名称', '')}」"
            is_new = True

        json_path = Path(LEDGER_JSON_PATH)
        excel_path = Path(LEDGER_EXCEL_PATH)
        old_json = json_path.read_bytes() if json_path.exists() else None
        old_excel = excel_path.read_bytes() if excel_path.exists() else None

        tmp_excel = None
        try:
            from utils.write_excel import write_ledger as write_legal_ledger
            with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=str(output_dir), delete=False) as tmp:
                tmp_excel = tmp.name
            write_legal_ledger(updated_cases, tmp_excel)
            save_cases_json(updated_cases)
            Path(tmp_excel).replace(excel_path)
        except Exception as e:
            if tmp_excel and os.path.exists(tmp_excel):
                try:
                    os.unlink(tmp_excel)
                except OSError:
                    pass
            if old_json is not None:
                atomic_write_bytes(json_path, old_json)
            elif json_path.exists():
                json_path.unlink()
            if old_excel is not None:
                atomic_write_bytes(excel_path, old_excel)
            elif excel_path.exists():
                excel_path.unlink()
            write_log(db, user, "ledger_write_failed", f"Ledger transaction failed: {e}", request)
            raise HTTPException(status_code=500, detail=f"台账写入失败：{e}")

    reply = (
        f"✅ {action_text}\n\n"
        f"📊 台账共 **{len(updated_cases)}** 个案件，Excel 已更新。\n\n"
        f"📁 文书已归档至：`{archive_dir}`"
    )
    history = load_history(user.id, req.session_id)
    history.append({"role": "assistant", "content": reply})
    save_history(history, user.id, req.session_id)

    write_log(db, user, "ledger_write", f"写入案件台账：{req.case_data.get('案件名称', '')}", request)
    return {"ok": True, "case_count": len(updated_cases), "reply": reply, "archive_dir": archive_dir}



# ── 清空台账（仅管理员）────────────────────────────────────────

@router.post("/clear")
def clear_ledger(
    request: Request,
    session_id: str = "",
    db: DBSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    txn_lock = Path(LEDGER_JSON_PATH).with_suffix(".txn")
    with file_lock(txn_lock):
        p = Path(LEDGER_JSON_PATH)
        if p.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = p.with_name(f"cases_backup_{ts}.json")
            p.replace(backup)
            msg = f"✅ 台账已清空，备份已保存至：`{backup}`"
        else:
            msg = "台账本来就是空的，无需清空。"
    write_log(db, user, "ledger_clear", "清空案件台账", request)
    history = load_history(user.id, session_id)
    history.append({"role": "assistant", "content": msg})
    save_history(history, user.id, session_id)
    return {"message": msg}


# ── 下载 Excel ────────────────────────────────────────────────

@router.get("/download-excel")
def download_ledger_excel():
    if not os.path.exists(LEDGER_EXCEL_PATH):
        from fastapi import HTTPException
        raise HTTPException(404, "台账文件不存在")
    return FileResponse(
        LEDGER_EXCEL_PATH,
        filename="诉讼案件台账.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
