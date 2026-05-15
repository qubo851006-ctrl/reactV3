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
from models import User
from routers.chat import load_history, save_history
from upload_validation import UploadValidationError, validate_pdf_upload
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

    def _process() -> dict[str, Any]:
        trace = PerfTrace("compliance.extract", user.id)
        try:
            with trace.step("extract_pdf_text"):
                text = extract_pdf_text(pdf_bytes, safe_name, vision_model)
            if not text.strip():
                raise ValueError("未能从 PDF 中提取可识别文本")
            with trace.step("load_responsible_persons"):
                persons = load_responsible_persons()
            with trace.step("extract_compliance_item"):
                return extract_compliance_item(text, persons)
        finally:
            trace.finish()

    try:
        item = await asyncio.to_thread(_process)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"合规审查信息提取失败：{e}")

    write_log(db, user, "compliance_extract", f"提取合规审查台账：{item.get('title', safe_name)}", request)
    return {"item": item}


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
