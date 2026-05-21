import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession

from auth_utils import get_current_user
from db import SessionLocal, get_db
from models import BackgroundTask, User
from task_runner import TERMINAL_STATUSES

router = APIRouter(prefix="/api/tasks")


def _can_read_task(task: BackgroundTask, user: User) -> bool:
    return user.role == "admin" or task.created_by == user.id


def serialize_task(task: BackgroundTask) -> dict:
    result = None
    if task.result_json:
        try:
            result = json.loads(task.result_json)
        except json.JSONDecodeError:
            result = None
    return {
        "task_id": task.task_id,
        "type": task.type,
        "status": task.status,
        "progress": task.progress,
        "message": task.message,
        "result": result,
        "error": task.error,
        "created_by": task.created_by,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


@router.get("/{task_id}")
def get_task(
    task_id: str,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
    if not task or not _can_read_task(task, user):
        raise HTTPException(status_code=404, detail="任务不存在")
    return serialize_task(task)


@router.get("")
def list_tasks(
    limit: int = 50,
    db: DBSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    safe_limit = max(1, min(200, int(limit or 50)))
    query = db.query(BackgroundTask).order_by(BackgroundTask.created_at.desc())
    if user.role != "admin":
        query = query.filter(BackgroundTask.created_by == user.id)
    tasks = query.limit(safe_limit).all()
    return {"tasks": [serialize_task(task) for task in tasks]}


@router.get("/{task_id}/events")
async def stream_task_events(
    task_id: str,
    user: User = Depends(get_current_user),
):
    async def events():
        for _ in range(120):
            db = SessionLocal()
            try:
                task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
                if not task or not _can_read_task(task, user):
                    yield "event: error\ndata: {\"error\":\"not_found\"}\n\n"
                    return
                payload = serialize_task(task)
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if task.status in TERMINAL_STATUSES:
                    return
            finally:
                db.close()
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")
