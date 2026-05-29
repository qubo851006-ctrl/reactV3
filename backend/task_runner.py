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


# Non-terminal statuses: tasks stuck here after a restart are orphaned, because
# the ThreadPoolExecutor that was running them died with the old process.
_NON_TERMINAL_STATUSES = ("queued", "running")


def reclaim_orphaned_tasks(db: DBSession | None = None) -> int:
    """Mark tasks left in queued/running as failed on startup.

    Background tasks run in an in-process ThreadPoolExecutor. When the process
    restarts (deploy, crash, manual restart), any task that was still queued or
    running has no thread behind it anymore, but its DB row stays stuck in that
    status forever — the UI shows a spinner that never resolves.

    Call this once on startup, after the DB is ready. It gives every orphan a
    clear terminal state so the user knows to re-submit. Idempotent: terminal
    tasks (succeeded/failed/cancelled) are never touched.

    Returns the number of tasks reclaimed.
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        orphans = (
            db.query(BackgroundTask)
            .filter(BackgroundTask.status.in_(_NON_TERMINAL_STATUSES))
            .all()
        )
        if not orphans:
            return 0
        now = _now()
        for task in orphans:
            task.status = "failed"
            task.message = "服务重启中断"
            task.error = "服务重启导致任务中断,请重新发起。"
            task.finished_at = now
            task.updated_at = now
        db.commit()
        logger.warning("启动回收孤儿后台任务 %d 个(原 queued/running)", len(orphans))
        return len(orphans)
    except Exception:
        logger.exception("回收孤儿后台任务失败")
        if db is not None:
            db.rollback()
        return 0
    finally:
        if own_session and db is not None:
            db.close()


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
