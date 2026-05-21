import json
import logging
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session as DBSession

from db import SessionLocal
from models import BackgroundTask

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
_EXECUTOR = ThreadPoolExecutor(max_workers=int(os.getenv("BACKGROUND_TASK_WORKERS", "2")))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_background_task(
    db: DBSession,
    *,
    task_type: str,
    created_by: int | None,
    message: str = "",
) -> BackgroundTask:
    task = BackgroundTask(
        task_id=f"task_{secrets.token_urlsafe(12)}",
        type=task_type,
        status="queued",
        progress=0,
        message=message,
        created_by=created_by,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


class TaskContext:
    def __init__(self, db: DBSession, task: BackgroundTask):
        self.db = db
        self.task = task

    def update(self, *, progress: int | None = None, message: str | None = None) -> None:
        if progress is not None:
            self.task.progress = max(0, min(100, int(progress)))
        if message is not None:
            self.task.message = message[:300]
        self.task.updated_at = _now()
        self.db.commit()


TaskWorker = Callable[[TaskContext, DBSession], dict[str, Any] | None]


def submit_background_task(task_id: str, worker: TaskWorker) -> None:
    _EXECUTOR.submit(_run_task, task_id, worker)


def _run_task(task_id: str, worker: TaskWorker) -> None:
    db = SessionLocal()
    try:
        task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
        if not task:
            logger.warning("background task missing before start: %s", task_id)
            return

        task.status = "running"
        task.progress = max(task.progress, 5)
        task.message = task.message or "任务处理中"
        task.started_at = _now()
        task.updated_at = _now()
        db.commit()

        ctx = TaskContext(db, task)
        result = worker(ctx, db) or {}

        task.status = "succeeded"
        task.progress = 100
        task.message = "完成"
        task.result_json = json.dumps(result, ensure_ascii=False)
        task.error = None
        task.finished_at = _now()
        task.updated_at = _now()
        db.commit()
    except Exception as exc:
        logger.exception("background task failed: %s", task_id)
        try:
            task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).first()
            if task:
                task.status = "failed"
                task.message = "失败"
                task.error = str(exc)[:1000]
                task.finished_at = _now()
                task.updated_at = _now()
                db.commit()
        except Exception:
            logger.exception("failed to persist background task failure: %s", task_id)
    finally:
        db.close()
