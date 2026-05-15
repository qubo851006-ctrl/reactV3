import asyncio
import os
import io
import base64
import tempfile
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from auth_utils import get_current_user
from audit_log import write_log
from db import get_db
from models import User
from routers.chat import load_history, save_history
from config import AUTH_LEDGER_PATH
from upload_validation import UploadValidationError, validate_pdf_upload
from perf_trace import PerfTrace

router = APIRouter(prefix="/api/auth-request", tags=["auth-request"])


class AuthLedgerRecordRequest(BaseModel):
    info: dict
    title: str
    session_id: str = ""


@router.post("/process")
async def process_auth_request(
    pdf_file: UploadFile = File(...),
    session_id: str = Form(""),
    vision_model: str = Form(""),
    request: Request = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from utils.auth_request_drafter import (
        extract_approval_info,
        draft_auth_documents,
        save_as_docx,
        save_auth_letter_as_docx,
    )
    from ledger_helpers import ocr_pdf_with_vision
    import pdfplumber

    pdf_bytes = await pdf_file.read()
    try:
        validate_pdf_upload(pdf_file.filename or "", pdf_file.content_type, pdf_bytes)
    except UploadValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    def _run_blocking() -> dict:
        """
        所有阻塞操作（PDF 解析、OCR、多次 LLM 调用、文件写入）统一在此函数中运行，
        通过 asyncio.to_thread 卸载到线程池，不阻塞事件循环。
        """
        nonlocal pdf_bytes, session_id, vision_model
        trace = PerfTrace("auth_request.process", user.id)

        try:
            # 提取文字
            pdf_text = ""
            with trace.step("pdf_text"):
                with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                    for page in pdf.pages:
                        t = page.extract_text()
                        if t:
                            pdf_text += t + "\n"
                pdf_text = pdf_text.strip()
            if not pdf_text:
                with trace.step("ocr"):
                    pdf_text = ocr_pdf_with_vision(pdf_bytes, model=vision_model)

            # AI 提取字段 + 生成文档
            with trace.step("extract_info"):
                info = extract_approval_info(pdf_text)
            with trace.step("draft_documents"):
                docs = draft_auth_documents(info)
            auth_content = docs["auth_content"]
            letter_content = docs["letter_content"]

            # 生成授权请示 Word
            with trace.step("write_docx"):
                with tempfile.NamedTemporaryFile(suffix=".docx", delete=False, prefix="授权请示_") as tmp:
                    docx_path = tmp.name
                save_as_docx(auth_content, docx_path)
                with open(docx_path, "rb") as f:
                    docx_b64 = base64.b64encode(f.read()).decode()
                os.unlink(docx_path)

            # 生成授权书 Word
            with trace.step("write_letter_docx"):
                with tempfile.NamedTemporaryFile(suffix=".docx", delete=False, prefix="授权书_") as tmp:
                    letter_path = tmp.name
                save_auth_letter_as_docx(letter_content, letter_path)
                with open(letter_path, "rb") as f:
                    letter_b64 = base64.b64encode(f.read()).decode()
                os.unlink(letter_path)

            project_name = info.get("项目名称") or "授权请示"
            title = "关于{}相关工作授权的请示".format(
                project_name[:15] if len(project_name) > 15 else project_name
            )

            return {
                "info": info,
                "auth_content": auth_content,
                "letter_content": letter_content,
                "docx_b64": docx_b64,
                "letter_b64": letter_b64,
                "project_name": project_name,
                "title": title,
            }
        finally:
            trace.finish()

    result = await asyncio.to_thread(_run_blocking)
    info = result["info"]
    auth_content = result["auth_content"]
    project_name = result["project_name"]

    write_log(db, user, "auth_request_process", f"生成授权请示：{project_name}", request)
    reply = "✅ 授权请示及授权书已生成！\n\n---\n\n{}".format(auth_content)
    history = await asyncio.to_thread(load_history, user.id, session_id)
    history.append({"role": "assistant", "content": reply})
    await asyncio.to_thread(save_history, history, user.id, session_id)

    return {
        "content": auth_content,
        "docx_base64": result["docx_b64"],
        "filename": "授权请示_{}.docx".format(project_name[:20]),
        "letter_content": result["letter_content"],
        "letter_base64": result["letter_b64"],
        "letter_filename": "授权书_{}.docx".format(project_name[:20]),
        "ledger_updated": False,
        "ledger_base64": None,
        "ledger_filename": None,
        "title": result["title"],
        "info": info,
    }


@router.post("/record-ledger")
def record_auth_ledger(
    body: AuthLedgerRecordRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from utils.auth_request_drafter import record_to_ledger

    ledger_updated = record_to_ledger(body.info, body.title, AUTH_LEDGER_PATH)
    ledger_b64 = None
    ledger_filename = None
    if ledger_updated:
        with open(AUTH_LEDGER_PATH, "rb") as f:
            ledger_b64 = base64.b64encode(f.read()).decode()
        ledger_filename = os.path.basename(AUTH_LEDGER_PATH)
    write_log(db, user, "auth_request_ledger_write", f"记录授权台账：{body.title}", request)
    reply = f"✅ 授权委托台账已记录：{body.title}"
    if body.session_id:
        history = load_history(user.id, body.session_id)
        history.append({"role": "assistant", "content": reply})
        save_history(history, user.id, body.session_id)
    return {
        "ledger_updated": ledger_updated,
        "ledger_base64": ledger_b64,
        "ledger_filename": ledger_filename,
        "reply": reply,
    }
