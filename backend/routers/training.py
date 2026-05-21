import asyncio
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from auth_utils import get_current_user
from audit_log import write_log
from db import get_db
from integrations.dingtalk import notify_task_failure, notify_task_success
from models import User
from routers.chat import load_history, save_history
from task_runner import create_background_task, submit_background_task
from upload_validation import UploadValidationError, validate_image_upload, validate_pdf_upload
from config import DATA_ROOT
from file_store import atomic_write_bytes, safe_child_path
from perf_trace import PerfTrace

router = APIRouter(prefix="/api/training", tags=["training"])
_TRAINING_PENDING_ROOT = Path(DATA_ROOT) / "_pending_training_uploads"
_TRAINING_PENDING_PREFIX = "training_"


def _training_pending_dir(pending_id: str) -> Path:
    if not pending_id.startswith(_TRAINING_PENDING_PREFIX) or not pending_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("无效的培训暂存编号")
    return safe_child_path(_TRAINING_PENDING_ROOT, pending_id)


def _create_training_pending_upload(notice_name: str, notice_bytes: bytes, signin_name: str, signin_bytes: bytes) -> str:
    pending_id = f"{_TRAINING_PENDING_PREFIX}{secrets.token_urlsafe(12)}"
    pending_dir = _training_pending_dir(pending_id)
    pending_dir.mkdir(parents=True, exist_ok=False)
    atomic_write_bytes(pending_dir / f"notice{Path(notice_name).suffix.lower() or '.pdf'}", notice_bytes)
    atomic_write_bytes(pending_dir / f"signin{Path(signin_name).suffix.lower() or '.img'}", signin_bytes)
    return pending_id


def _archive_pending_training_upload(pending_id: str, category: str, date: str, topic: str) -> str:
    from utils.archiver import archive_files

    pending_dir = _training_pending_dir(pending_id)
    if not pending_dir.exists():
        raise ValueError("培训暂存文件不存在或已过期")
    notice_files = list(pending_dir.glob("notice.*"))
    signin_files = list(pending_dir.glob("signin.*"))
    if not notice_files or not signin_files:
        raise ValueError("培训暂存文件不完整")
    archive_path = archive_files(
        notice_path=str(notice_files[0]),
        sign_in_path=str(signin_files[0]),
        category=category,
        date=date,
        topic=topic,
    )
    shutil.rmtree(pending_dir, ignore_errors=True)
    return archive_path


def _calc_duration_hours(start: str, end: str, days: int) -> float:
    """计算培训时长（课时），1课时=40分钟，支持多天培训。"""
    try:
        s = datetime.strptime(start.strip(), "%H:%M")
        e = datetime.strptime(end.strip(), "%H:%M")
        if e <= s:
            return 0.0
        minutes_per_day = int((e - s).seconds / 60)
        total_minutes = minutes_per_day * max(days, 1)
        return round(total_minutes / 40, 1)
    except Exception:
        return 0.0


def _extract_training_time(notice_text: str) -> dict:
    """
    用 LLM 从培训通知文字中提取开始时间、结束时间和天数。
    返回: {start_time, end_time, days, duration_hours}
    提取失败时返回空字符串和 0.0，前端可手动填写。
    """
    import warnings
    import httpx
    from dotenv import load_dotenv
    from openai import OpenAI
    from config import AI_HTTP_VERIFY_SSL
    from llm_client import build_ai_http_headers

    warnings.filterwarnings("ignore")
    load_dotenv(override=True)

    empty = {"start_time": "", "end_time": "", "days": 1, "duration_hours": 0.0}
    if not notice_text.strip():
        return empty

    try:
        client = OpenAI(
            api_key=os.getenv("AIRCHINA_API_KEY"),
            base_url=os.getenv("AIRCHINA_BASE_URL"),
            http_client=httpx.Client(verify=AI_HTTP_VERIFY_SSL, headers=build_ai_http_headers()),
        )
        model = os.getenv("MODEL_CLASSIFY", "qwen2.5-72b")

        prompt = f"""请从以下培训通知文字中提取培训时间信息。

培训通知内容：
{notice_text}

请严格按照以下格式输出，不要有任何多余内容：
开始时间：HH:MM
结束时间：HH:MM
天数：N

说明：
- 时间格式必须是24小时制 HH:MM，例如 09:00、14:30
- 天数是整数，单天培训填1
- 如果通知中没有明确的时间信息，全部填写为空：开始时间：、结束时间：、天数：1
"""

        from llm_audit import traced_complete
        response = traced_complete(
            client,
            scene="training_extract_time",
            prompt_template_id="training.extract_time.v1",
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.choices[0].message.content.strip()

        start_match = re.search(r"开始时间[：:]\s*(\d{1,2}:\d{2})", text)
        end_match = re.search(r"结束时间[：:]\s*(\d{1,2}:\d{2})", text)
        days_match = re.search(r"天数[：:]\s*(\d+)", text)

        start_time = start_match.group(1) if start_match else ""
        end_time = end_match.group(1) if end_match else ""
        days = int(days_match.group(1)) if days_match else 1

        # 补零对齐 HH:MM
        if start_time and ":" in start_time:
            h, m = start_time.split(":")
            start_time = f"{int(h):02d}:{m}"
        if end_time and ":" in end_time:
            h, m = end_time.split(":")
            end_time = f"{int(h):02d}:{m}"

        duration_hours = _calc_duration_hours(start_time, end_time, days) if start_time and end_time else 0.0

        return {
            "start_time": start_time,
            "end_time": end_time,
            "days": days,
            "duration_hours": duration_hours,
        }
    except Exception:
        return empty


def _run_training_extraction(
    notice_bytes: bytes,
    signin_bytes: bytes,
    notice_name: str,
    signin_name: str,
    vision_model: str,
) -> dict:
    """
    同步耗时操作（PDF 解析 + 两次 LLM 调用）统一在此函数中完成，
    由调用方通过 asyncio.to_thread 卸载到线程池，不阻塞事件循环。
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from utils.pdf_reader import extract_pdf_text
    from utils.image_analyzer import count_attendees
    from utils.classifier import classify_training
    from utils.excel_writer import EXCEL_PATH

    from llm_audit.context import collect_traces

    trace = PerfTrace("training.extract")
    try:
        with collect_traces() as bucket:
            with tempfile.TemporaryDirectory() as tmpdir:
                notice_path = os.path.join(tmpdir, notice_name)
                signin_path = os.path.join(tmpdir, signin_name)
                with trace.step("write_upload_temp_files"):
                    with open(notice_path, "wb") as f:
                        f.write(notice_bytes)
                    with open(signin_path, "wb") as f:
                        f.write(signin_bytes)

                with trace.step("extract_pdf_text"):
                    notice_text = extract_pdf_text(notice_path)
                with trace.step("count_attendees"):
                    sign_in_info = count_attendees(signin_path, model=vision_model)
                with trace.step("classify_training"):
                    category = classify_training(notice_text, sign_in_info["topic"])
                with trace.step("extract_training_time"):
                    time_info = _extract_training_time(notice_text)
                with trace.step("stage_pending_archive"):
                    pending_upload_id = _create_training_pending_upload(notice_name, notice_bytes, signin_name, signin_bytes)
        llm_trace_ids = list(bucket.ids)
    finally:
        trace.finish()

    return {
        "topic": sign_in_info["topic"] or "",
        "location": sign_in_info["location"] or "",
        "date": sign_in_info["date"] or "",
        "count": sign_in_info["count"],
        "category": category,
        "start_time": time_info["start_time"],
        "end_time": time_info["end_time"],
        "duration_hours": time_info["duration_hours"],
        "archive_path": "",
        "pending_upload_id": pending_upload_id,
        "excel_path": EXCEL_PATH,
        "confidence": sign_in_info.get("confidence", "high"),
        "reflection_note": sign_in_info.get("reflection_note", ""),
        "llm_trace_ids": llm_trace_ids,
    }


# ── 提取（不写入台账）────────────────────────────────────────

@router.post("/extract")
async def extract_training(
    notice_pdf: UploadFile = File(...),
    signin_img: UploadFile = File(...),
    department: str = Form(""),
    vision_model: str = Form(""),
    request: Request = None,
    user: User = Depends(get_current_user),
):
    """
    提取培训信息并归档文件，但不写入 Excel。
    返回提取结果供前端展示确认。
    耗时的 PDF 解析和 LLM 调用通过 asyncio.to_thread 卸载到线程池，不阻塞事件循环。
    """
    notice_bytes = await notice_pdf.read()
    signin_bytes = await signin_img.read()
    try:
        notice_name = validate_pdf_upload(notice_pdf.filename or "", notice_pdf.content_type, notice_bytes)
        signin_name = validate_image_upload(signin_img.filename or "", signin_img.content_type, signin_bytes)
    except UploadValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await asyncio.to_thread(
            _run_training_extraction,
            notice_bytes, signin_bytes, notice_name, signin_name, vision_model,
        )
    except Exception as e:
        notify_task_failure(
            task="培训信息识别",
            summary=str(e)[:160],
            user=user,
            stage="AI 识别",
        )
        raise

    notify_task_success(
        task="培训信息识别",
        summary=str(result.get("topic") or notice_name)[:160],
        user=user,
        stage="AI 识别",
    )
    return {**result, "department": department or ""}


@router.post("/extract-task")
async def start_training_extract_task(
    notice_pdf: UploadFile = File(...),
    signin_img: UploadFile = File(...),
    department: str = Form(""),
    vision_model: str = Form(""),
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notice_bytes = await notice_pdf.read()
    signin_bytes = await signin_img.read()
    try:
        notice_name = validate_pdf_upload(notice_pdf.filename or "", notice_pdf.content_type, notice_bytes)
        signin_name = validate_image_upload(signin_img.filename or "", signin_img.content_type, signin_bytes)
    except UploadValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task = create_background_task(
        db,
        task_type="training_extract",
        created_by=user.id,
        message="已接收文件，等待识别",
    )

    def _worker(ctx, task_db: DBSession) -> dict:
        task_user = task_db.query(User).filter(User.id == user.id).first()
        if not task_user:
            raise RuntimeError("发起用户不存在")
        try:
            ctx.update(progress=15, message="正在识别培训通知和签到表")
            result = _run_training_extraction(
                notice_bytes,
                signin_bytes,
                notice_name,
                signin_name,
                vision_model,
            )
            result = {**result, "department": department or ""}
            write_log(
                task_db,
                task_user,
                "training_extract",
                f"识别培训记录：{result.get('topic') or notice_name}",
                None,
            )
            notify_task_success(
                task="培训信息识别",
                summary=str(result.get("topic") or notice_name)[:160],
                user=task_user,
                stage="AI 识别",
            )
            return result
        except Exception as exc:
            notify_task_failure(
                task="培训信息识别",
                summary=str(exc)[:160],
                user=task_user,
                stage="AI 识别",
            )
            raise

    submit_background_task(task.task_id, _worker)
    return {"ok": True, "task_id": task.task_id}


# ── 确认写入台账 ──────────────────────────────────────────────

class TrainingWriteRequest(BaseModel):
    topic: str
    location: str
    date: str
    department: str
    count: int
    category: str
    archive_path: str
    pending_upload_id: str = ""
    start_time: str = ""
    end_time: str = ""
    duration_hours: float = 0.0
    session_id: str = ""


@router.post("/write")
def write_training(
    req: TrainingWriteRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    用户确认后写入 Excel 台账并更新对话历史。
    """
    from utils.excel_writer import append_record, EXCEL_PATH

    archive_path = req.archive_path
    if req.pending_upload_id:
        archive_path = _archive_pending_training_upload(req.pending_upload_id, req.category, req.date, req.topic)

    append_record(
        date=req.date,
        topic=req.topic,
        location=req.location,
        department=req.department,
        count=req.count,
        duration_hours=req.duration_hours,
        category=req.category,
        archive_path=archive_path,
    )

    duration_display = f"{req.duration_hours} 课时" if req.duration_hours > 0 else "未填写"
    reply = (
        f"✅ 培训记录已写入台账！\n\n"
        f"| 字段 | 内容 |\n|------|------|\n"
        f"| 培训主题 | {req.topic} |\n"
        f"| 培训地点 | {req.location} |\n"
        f"| 培训日期 | {req.date} |\n"
        f"| 主办部门 | {req.department or '未填写'} |\n"
        f"| 参与人数 | **{req.count} 人** |\n"
        f"| 培训时长 | {duration_display} |\n"
        f"| 培训类别 | {req.category} |\n"
        f"| 归档路径 | `{archive_path}` |"
    )
    write_log(db, user, "training_write", f"写入培训记录：{req.topic}", request)
    history = load_history(user.id, req.session_id)
    history.append({"role": "assistant", "content": reply})
    save_history(history, user.id, req.session_id)
    return {"ok": True, "excel_path": EXCEL_PATH}


# ── 下载统计表 ────────────────────────────────────────────────

@router.get("/download-excel")
def download_excel():
    from utils.excel_writer import EXCEL_PATH
    if not os.path.exists(EXCEL_PATH):
        from fastapi import HTTPException
        raise HTTPException(404, "统计表不存在")
    return FileResponse(
        EXCEL_PATH,
        filename="培训统计表.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
