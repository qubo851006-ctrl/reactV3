# -*- coding: utf-8 -*-
import asyncio
import re
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DBSession

from auth_utils import get_current_user
from audit_log import write_log
from db import get_db
from integrations.dingtalk import notify_task_failure, notify_task_success
from models import User
from file_store import atomic_write_bytes, file_lock
from task_runner import create_background_task, submit_background_task
from upload_validation import validate_excel_upload
from utils.excel_merger import merge_ledgers

router = APIRouter(prefix="/api/ledger-merge")

DATA_DIR = Path(__file__).parent.parent.parent / "data"
MERGED_DIR = DATA_DIR / "合并台账"
_RESULT_ID_RE = re.compile(r"^merge_[A-Za-z0-9_-]{8,80}$")


def _validate_result_id(result_id: str) -> str:
    if not _RESULT_ID_RE.fullmatch(result_id or ""):
        raise ValueError("无效的合并结果编号")
    return result_id


def _user_merge_dir(user_id: int) -> Path:
    return MERGED_DIR / f"user_{user_id}"


def _result_file_for(user_id: int, result_id: str) -> Path:
    safe_id = _validate_result_id(result_id)
    user_dir = _user_merge_dir(user_id).resolve()
    path = (user_dir / f"{safe_id}.xlsx").resolve()
    if not path.is_relative_to(user_dir):
        raise ValueError("合并结果路径越界")
    return path


def _latest_file_for(user_id: int) -> Path:
    return _user_merge_dir(user_id) / "latest.xlsx"


async def _read_and_validate_uploads(
    contract_file: UploadFile,
    purchase_file: Optional[UploadFile],
    finance_file: Optional[UploadFile],
) -> tuple[bytes, bytes | None, bytes | None]:
    contract_bytes = await contract_file.read()
    purchase_bytes = await purchase_file.read() if purchase_file and purchase_file.filename else None
    finance_bytes = await finance_file.read() if finance_file and finance_file.filename else None

    validate_excel_upload(contract_file.filename or "", contract_file.content_type, contract_bytes)
    if purchase_bytes is not None and purchase_file:
        validate_excel_upload(purchase_file.filename or "", purchase_file.content_type, purchase_bytes)
    if finance_bytes is not None and finance_file:
        validate_excel_upload(finance_file.filename or "", finance_file.content_type, finance_bytes)
    return contract_bytes, purchase_bytes, finance_bytes


def _merge_and_save_for_user(
    user_id: int,
    contract_bytes: bytes,
    purchase_bytes: bytes | None,
    finance_bytes: bytes | None,
    *,
    on_progress=None,
) -> dict:
    if on_progress:
        on_progress(30, "正在合并台账")
    merged_bytes, stats = merge_ledgers(contract_bytes, purchase_bytes, finance_bytes)
    if on_progress:
        on_progress(80, "正在保存合并结果")

    result_id = f"merge_{secrets.token_urlsafe(12)}"
    result_file = _result_file_for(user_id, result_id)
    latest_file = _latest_file_for(user_id)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(result_file):
        atomic_write_bytes(result_file, merged_bytes)
    with file_lock(latest_file):
        atomic_write_bytes(latest_file, merged_bytes)
    return {**stats, "result_id": result_id}


@router.post("/merge-task")
async def start_merge_task(
    contract_file: UploadFile = File(...),
    purchase_file: Optional[UploadFile] = File(None),
    finance_file: Optional[UploadFile] = File(None),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        contract_bytes, purchase_bytes, finance_bytes = await _read_and_validate_uploads(
            contract_file,
            purchase_file,
            finance_file,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task = create_background_task(
        db,
        task_type="ledger_merge",
        created_by=user.id,
        message="已接收文件，等待合并",
    )

    def _worker(ctx, task_db: DBSession) -> dict:
        task_user = task_db.query(User).filter(User.id == user.id).first()
        if not task_user:
            raise RuntimeError("发起用户不存在")
        try:
            ctx.update(progress=15, message="正在读取台账")
            stats = _merge_and_save_for_user(
                task_user.id,
                contract_bytes,
                purchase_bytes,
                finance_bytes,
                on_progress=lambda progress, message: ctx.update(progress=progress, message=message),
            )
            write_log(
                task_db,
                task_user,
                "ledger_merge",
                f"合并三台账，合同条数：{stats.get('total_contract', 0)}",
                None,
            )
            notify_task_success(
                task="三台账合并",
                summary=f"合同条数：{stats.get('total_contract', 0)}",
                user=task_user,
                stage="合并生成",
            )
            return {"ok": True, **stats}
        except Exception as exc:
            notify_task_failure(
                task="三台账合并",
                summary=str(exc)[:160],
                user=task_user,
                stage="合并生成",
            )
            raise

    submit_background_task(task.task_id, _worker)
    return {"ok": True, "task_id": task.task_id}


@router.post("/merge")
async def merge_excel(
    contract_file: UploadFile = File(...),
    purchase_file: Optional[UploadFile] = File(None),
    finance_file: Optional[UploadFile] = File(None),
    request: Request = None,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        contract_bytes, purchase_bytes, finance_bytes = await _read_and_validate_uploads(
            contract_file,
            purchase_file,
            finance_file,
        )

        stats = await asyncio.to_thread(
            _merge_and_save_for_user,
            user.id,
            contract_bytes,
            purchase_bytes,
            finance_bytes,
        )

        write_log(db, user, "ledger_merge", f"合并三台账，合同条数：{stats.get('total_contract', 0)}", request)
        notify_task_success(
            task="三台账合并",
            summary=f"合同条数：{stats.get('total_contract', 0)}",
            user=user,
            stage="合并生成",
        )
        return {"ok": True, **stats}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        notify_task_failure(
            task="三台账合并",
            summary=str(e)[:160],
            user=user,
            stage="合并生成",
        )
        raise HTTPException(status_code=500, detail=f"合并失败：{e}")


@router.get("/download")
def download_merged(
    result_id: str = Query(default=""),
    user: User = Depends(get_current_user),
):
    try:
        path = _result_file_for(user.id, result_id) if result_id else _latest_file_for(user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not path.exists():
        raise HTTPException(status_code=404, detail="合并文件不存在，请先执行合并操作。")
    return FileResponse(
        path=str(path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="合并台账.xlsx",
    )
