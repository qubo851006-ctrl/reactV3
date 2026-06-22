import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from audit_log import write_log
from auth_utils import get_current_user, require_admin
from config import COMPLIANCE_LEDGER_EXCEL_PATH, COMPLIANCE_LEDGER_JSON_PATH
from db import get_db
from file_store import atomic_write_bytes, atomic_write_text, file_lock
from integrations.dingtalk import notify_task_failure, notify_task_success
from models import User
from routers.chat import load_history, save_history
from task_runner import create_background_task, submit_background_task
from upload_validation import UploadValidationError, validate_excel_upload, validate_pdf_upload
from perf_trace import PerfTrace
from utils.compliance_ledger import (
    create_compliance_workbook,
    extract_compliance_item,
    extract_pdf_text,
    load_records,
    load_responsible_persons,
    normalize_extracted_item,
    save_responsible_persons,
    upsert_record,
)
from utils.ledger_importer import (
    create_pending_import,
    load_pending_import,
    make_preview,
    normalize_key,
    parse_compliance_rows,
)

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


class ResponsiblePersonsUpdate(BaseModel):
    persons: dict[str, str]


class ComplianceWriteRequest(BaseModel):
    title: str
    procedure: str
    undertaking_department: str = "法务合规部"
    background_materials: list[str] = Field(default_factory=list)
    review_rows: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    session_id: str = ""


class ComplianceImportConfirmRequest(BaseModel):
    import_token: str
    session_id: str = ""


def _compliance_existing_keys() -> set[str]:
    return {normalize_key(record.get("title")) for record in load_records(COMPLIANCE_LEDGER_JSON_PATH) if normalize_key(record.get("title"))}


def _run_compliance_extraction(
    pdf_bytes: bytes,
    safe_name: str,
    vision_model: str,
    user_id: int,
    *,
    on_progress=None,
) -> tuple[dict[str, Any], list[str]]:
    from llm_audit.context import collect_traces

    trace = PerfTrace("compliance.extract", user_id)

    def progress(value: int, message: str) -> None:
        if on_progress:
            on_progress(value, message)

    try:
        with collect_traces() as bucket:
            progress(20, "正在解析合规审查 PDF")
            with trace.step("extract_pdf_text"):
                text = extract_pdf_text(pdf_bytes, safe_name, vision_model)
            if not text.strip():
                raise ValueError("未能从 PDF 中提取可识别文本")
            progress(45, "正在读取部门负责人配置")
            with trace.step("load_responsible_persons"):
                persons = load_responsible_persons()
            progress(70, "正在抽取合规审查信息")
            with trace.step("extract_compliance_item"):
                item = extract_compliance_item(text, persons)
        return item, list(bucket.ids)
    finally:
        trace.finish()


@router.get("/responsible-persons")
def get_responsible_persons(_: User = Depends(get_current_user)):
    return {"persons": load_responsible_persons()}


@router.put("/responsible-persons")
def update_responsible_persons(
    body: ResponsiblePersonsUpdate,
    _: User = Depends(require_admin),
):
    return {"persons": save_responsible_persons(body.persons)}


@router.post("/extract")
async def extract_compliance(
    pdf_file: UploadFile = File(...),
    vision_model: str = Form(""),
    request: Request = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pdf_bytes = await pdf_file.read()
    try:
        safe_name = validate_pdf_upload(pdf_file.filename or "", pdf_file.content_type, pdf_bytes)
    except UploadValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        item, llm_trace_ids = await asyncio.to_thread(
            _run_compliance_extraction,
            pdf_bytes,
            safe_name,
            vision_model,
            user.id,
        )
    except Exception as e:
        notify_task_failure(
            task="合规审查信息识别",
            summary=str(e)[:160],
            user=user,
            stage="AI 提取",
        )
        raise HTTPException(status_code=502, detail=f"合规审查信息提取失败：{e}")

    write_log(db, user, "compliance_extract", f"提取合规审查台账：{item.get('title', safe_name)}", request)
    notify_task_success(
        task="合规审查信息识别",
        summary=str(item.get("title", safe_name))[:160],
        user=user,
        stage="AI 提取",
    )
    return {"item": item, "llm_trace_ids": llm_trace_ids}


@router.post("/extract-task")
async def start_compliance_extract_task(
    pdf_file: UploadFile = File(...),
    vision_model: str = Form(""),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pdf_bytes = await pdf_file.read()
    try:
        safe_name = validate_pdf_upload(pdf_file.filename or "", pdf_file.content_type, pdf_bytes)
    except UploadValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task = create_background_task(
        db,
        task_type="compliance_extract",
        created_by=user.id,
        message="已接收文件，等待识别",
    )

    def _worker(ctx, task_db: DBSession) -> dict:
        task_user = task_db.query(User).filter(User.id == user.id).first()
        if not task_user:
            raise RuntimeError("发起用户不存在")
        try:
            item, llm_trace_ids = _run_compliance_extraction(
                pdf_bytes,
                safe_name,
                vision_model,
                task_user.id,
                on_progress=lambda progress, message: ctx.update(progress=progress, message=message),
            )
            write_log(
                task_db,
                task_user,
                "compliance_extract",
                f"提取合规审查台账：{item.get('title', safe_name)}",
                None,
            )
            notify_task_success(
                task="合规审查信息识别",
                summary=str(item.get("title", safe_name))[:160],
                user=task_user,
                stage="AI 提取",
            )
            return {"item": item, "llm_trace_ids": llm_trace_ids}
        except Exception as exc:
            notify_task_failure(
                task="合规审查信息识别",
                summary=str(exc)[:160],
                user=task_user,
                stage="AI 提取",
            )
            raise

    submit_background_task(task.task_id, _worker)
    return {"ok": True, "task_id": task.task_id}


@router.post("/write")
def write_compliance(
    body: ComplianceWriteRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    body_data = body.model_dump() if hasattr(body, "model_dump") else body.dict()
    record = normalize_extracted_item(body_data)
    txn_lock = Path(COMPLIANCE_LEDGER_JSON_PATH).with_suffix(".txn")
    with file_lock(txn_lock):
        trace = PerfTrace("compliance.write", user.id)
        json_path = Path(COMPLIANCE_LEDGER_JSON_PATH)
        excel_path = Path(COMPLIANCE_LEDGER_EXCEL_PATH)
        old_json = json_path.read_bytes() if json_path.exists() else None
        old_excel = excel_path.read_bytes() if excel_path.exists() else None
        tmp_excel = None
        try:
            with trace.step("load_records"):
                records = load_records(json_path)
            records, saved_record, updated_existing = upsert_record(records, record)
            excel_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=str(excel_path.parent), delete=False) as tmp:
                tmp_excel = tmp.name
            with trace.step("create_workbook"):
                create_compliance_workbook(records, tmp_excel)
            with trace.step("commit_files"):
                atomic_write_text(json_path, json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
                Path(tmp_excel).replace(excel_path)
            sequence = saved_record.get("sequence", len(records))
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
            write_log(db, user, "compliance_write_failed", f"合规审查台账写入失败：{e}", request)
            raise HTTPException(status_code=500, detail=f"合规审查台账写入失败：{e}")
        finally:
            trace.finish()

    action_text = "已更新原有事项" if updated_existing else "已新增"
    reply = f"✅ 合规审查工作台账已更新！{action_text}第 {sequence} 项：{record.get('title', '')}"
    if body.session_id:
        history = load_history(user.id, body.session_id)
        history.append({"role": "assistant", "content": reply})
        save_history(history, user.id, body.session_id)
    write_log(db, user, "compliance_write", f"写入合规审查台账：{record.get('title', '')}", request)
    return {"ok": True, "count": len(records), "sequence": sequence, "reply": reply}


@router.post("/import-preview")
async def preview_compliance_import(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    file_bytes = await file.read()
    try:
        validate_excel_upload(file.filename or "", file.content_type, file_bytes)
        records, invalid_rows = parse_compliance_rows(file_bytes)
        records = [normalize_extracted_item(record) for record in records]
    except (UploadValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    token = create_pending_import(user.id, "compliance", {"records": records, "invalid_rows": invalid_rows})
    return make_preview(
        records=records,
        invalid_rows=invalid_rows,
        existing_keys=_compliance_existing_keys(),
        key_fn=lambda r: normalize_key(r.get("title")),
        import_token=token,
    )


@router.post("/import-confirm")
def confirm_compliance_import(
    body: ComplianceImportConfirmRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        pending = load_pending_import(user.id, "compliance", body.import_token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    txn_lock = Path(COMPLIANCE_LEDGER_JSON_PATH).with_suffix(".txn")
    with file_lock(txn_lock):
        json_path = Path(COMPLIANCE_LEDGER_JSON_PATH)
        excel_path = Path(COMPLIANCE_LEDGER_EXCEL_PATH)
        old_json = json_path.read_bytes() if json_path.exists() else None
        old_excel = excel_path.read_bytes() if excel_path.exists() else None
        tmp_excel = None
        inserts = 0
        updates = 0
        try:
            records = load_records(json_path)
            for raw_record in pending.get("records") or []:
                before_count = len(records)
                records, _, updated_existing = upsert_record(records, normalize_extracted_item(raw_record))
                if updated_existing:
                    updates += 1
                elif len(records) > before_count:
                    inserts += 1
            excel_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=str(excel_path.parent), delete=False) as tmp:
                tmp_excel = tmp.name
            create_compliance_workbook(records, tmp_excel)
            atomic_write_text(json_path, json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
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
            write_log(db, user, "compliance_import_failed", f"合规审查台账导入失败：{e}", request)
            raise HTTPException(status_code=500, detail=f"合规审查台账导入失败：{e}")

    reply = f"✅ 历史合规审查台账导入完成：新增 {inserts} 项，更新 {updates} 项。"
    if body.session_id:
        history = load_history(user.id, body.session_id)
        history.append({"role": "assistant", "content": reply})
        save_history(history, user.id, body.session_id)
    write_log(db, user, "compliance_import", f"导入历史合规审查台账：新增 {inserts}，更新 {updates}", request)
    return {"ok": True, "count": len(records), "inserts": inserts, "updates": updates, "reply": reply}


@router.get("/download")
def download_compliance(_: User = Depends(get_current_user)):
    path = Path(COMPLIANCE_LEDGER_EXCEL_PATH)
    if not path.exists():
        records = load_records(COMPLIANCE_LEDGER_JSON_PATH)
        if not records:
            raise HTTPException(status_code=404, detail="合规审查台账不存在，请先生成台账。")
        create_compliance_workbook(records, path)
    return FileResponse(
        path=str(path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="合规审查工作台账.xlsx",
    )
