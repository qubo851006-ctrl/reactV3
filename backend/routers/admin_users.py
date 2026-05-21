import hashlib
import os
import re
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from auth_utils import require_admin
from db import engine, get_db
from integrations.dingtalk import send_dingtalk_notification
from integrations.dingtalk.enterprise import get_access_token
from integrations.dingtalk.org_sync import sync_dingtalk_org
from llm_audit.db import get_audit_engine
from models import AuditLog, BackgroundTask, DingTalkSyncLog, NotificationLog, User, UserSession
from runtime_status import STARTED_AT

router = APIRouter(prefix="/api/admin", tags=["admin"])
ROOT_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = Path(os.getenv("V3_LOG_DIR", str(ROOT_DIR / "logs")))
_SECRET_RE = re.compile(r"(?i)(secret|token|key|password|authorization|cookie)=([^\\s&]+)")


def _active_sessions(u: User) -> int:
    now = datetime.now(timezone.utc)
    return sum(
        1
        for s in u.sessions
        if not s.revoked_at
        and (s.expires_at.replace(tzinfo=timezone.utc) if s.expires_at.tzinfo is None else s.expires_at) > now
    )


def _redact_log_line(line: str) -> str:
    line = _SECRET_RE.sub(r"\1=***", line.strip())
    return line[-500:]


def _run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
        return (result.stdout or result.stderr).strip()
    except Exception:
        return ""


def _check_sqlalchemy_engine(db_engine) -> dict:
    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "backend": db_engine.url.get_backend_name(), "error": ""}
    except Exception as exc:
        backend = getattr(getattr(db_engine, "url", None), "get_backend_name", lambda: "unknown")()
        return {"ok": False, "backend": backend, "error": str(exc)[:300]}


def _recent_error_logs(limit: int = 20) -> list[dict]:
    patterns = ["*.err.log", "*.log"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(LOG_DIR.glob(pattern))
    files = sorted({p for p in files if p.is_file()}, key=lambda p: p.stat().st_mtime, reverse=True)[:6]
    entries: list[dict] = []
    markers = ("ERROR", "Traceback", "Exception", "failed", "失败", "[E]")
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
        except Exception:
            continue
        for line in reversed(lines):
            if any(marker in line for marker in markers):
                entries.append({
                    "file": path.name,
                    "line": _redact_log_line(line),
                    "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                })
                if len(entries) >= limit:
                    return entries
    return entries


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _configured(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _read_app_version() -> str:
    if os.getenv("V3_APP_VERSION"):
        return os.getenv("V3_APP_VERSION", "")
    version_file = ROOT_DIR / "frontend" / "src" / "versionHistory.ts"
    try:
        text_body = version_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    match = re.search(r"version:\s*'([^']+)'", text_body)
    return match.group(1) if match else ""


@router.get("/users")
def list_users(db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    users = db.query(User).order_by(User.name).all()
    return {
        "users": [
            {
                "id": u.id,
                "name": u.name,
                "department": u.department,
                "role": u.role,
                "status": u.status,
                "dingtalk_user_id": u.dingtalk_user_id,
                "dingtalk_union_id": u.dingtalk_union_id,
                "dingtalk_dept_ids": u.dingtalk_dept_ids,
                "dingtalk_title": u.dingtalk_title,
                "dingtalk_mobile_tail": u.dingtalk_mobile_tail,
                "dingtalk_active": u.dingtalk_active,
                "dingtalk_synced_at": u.dingtalk_synced_at,
                "last_login_at": u.last_login_at,
                "active_sessions": _active_sessions(u),
            }
            for u in users
        ]
    }


@router.get("/ops/health")
def ops_health(db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    main_db = _check_sqlalchemy_engine(engine)
    audit_engine = get_audit_engine()
    audit_db = (
        _check_sqlalchemy_engine(audit_engine)
        if audit_engine is not None
        else {"ok": False, "backend": "not_configured", "error": "LLM_AUDIT_DATABASE_URL not configured"}
    )
    failed_tasks = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.status == "failed")
        .order_by(BackgroundTask.finished_at.desc().nullslast(), BackgroundTask.updated_at.desc())
        .limit(10)
        .all()
    )
    return {
        "version": {
            "app_version": _read_app_version(),
            "branch": _run_git(["branch", "--show-current"]) or "unknown",
            "commit": _run_git(["rev-parse", "--short", "HEAD"]) or "unknown",
            "commit_full": _run_git(["rev-parse", "HEAD"]) or "unknown",
            "commit_time": _run_git(["log", "-1", "--format=%cI"]) or "",
        },
        "runtime": {
            "started_at": STARTED_AT.isoformat(),
            "server_time": datetime.now(timezone.utc).isoformat(),
        },
        "databases": {
            "main": main_db,
            "llm_audit": audit_db,
        },
        "dingtalk": {
            "notify_enabled": _env_flag("DINGTALK_NOTIFY_ENABLED"),
            "webhook_url_configured": _configured("DINGTALK_WEBHOOK_URL"),
            "webhook_secret_configured": _configured("DINGTALK_WEBHOOK_SECRET"),
            "enterprise_enabled": _env_flag("DINGTALK_ENTERPRISE_ENABLED"),
            "work_notice_enabled": _env_flag("DINGTALK_WORK_NOTICE_ENABLED"),
            "org_sync_enabled": _env_flag("DINGTALK_ORG_SYNC_ENABLED"),
            "sso_enabled": _env_flag("DINGTALK_SSO_ENABLED"),
            "corp_id_configured": _configured("DINGTALK_CORP_ID"),
            "app_key_configured": _configured("DINGTALK_APP_KEY"),
            "app_secret_configured": _configured("DINGTALK_APP_SECRET"),
            "agent_id_configured": _configured("DINGTALK_AGENT_ID"),
        },
        "recent_errors": _recent_error_logs(),
        "recent_failed_tasks": [
            {
                "task_id": task.task_id,
                "type": task.type,
                "message": task.message,
                "error": task.error,
                "created_by": task.created_by,
                "created_at": task.created_at,
                "started_at": task.started_at,
                "finished_at": task.finished_at,
                "updated_at": task.updated_at,
            }
            for task in failed_tasks
        ],
    }


class UserCreate(BaseModel):
    name: str
    department: str = "法务部"
    role: str = "user"


@router.post("/users")
def create_user(
    body: UserCreate,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    if db.query(User).filter_by(name=body.name.strip()).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    code = str(1000 + secrets.randbelow(9000))
    user = User(
        name=body.name.strip(),
        department=body.department,
        role=body.role,
        short_code_hash=hashlib.sha256(code.encode()).hexdigest(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user": {"id": user.id, "name": user.name}, "short_code": code}


class UserUpdate(BaseModel):
    department: str | None = None
    role: str | None = None
    status: str | None = None
    dingtalk_user_id: str | None = None
    dingtalk_union_id: str | None = None


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdate,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.department is not None:
        user.department = body.department
    if body.role is not None:
        user.role = body.role
    if body.status is not None:
        user.status = body.status
    if body.dingtalk_user_id is not None:
        user.dingtalk_user_id = body.dingtalk_user_id.strip() or None
    if body.dingtalk_union_id is not None:
        user.dingtalk_union_id = body.dingtalk_union_id.strip() or None
    db.commit()
    return {"ok": True}


@router.post("/dingtalk/test-notification")
def test_dingtalk_notification(user: User = Depends(require_admin)):
    sent = send_dingtalk_notification(
        title="V3 钉钉通知测试",
        summary="管理员从 V3 发起的钉钉连通性测试",
        level="success",
        user_name=user.name,
        at_user_id=user.dingtalk_user_id or "",
        session_id="admin-dingtalk-test",
    )
    return {"ok": sent}


@router.post("/dingtalk/test-work-notice")
def test_dingtalk_work_notice(user: User = Depends(require_admin)):
    sent = send_dingtalk_notification(
        title="V3 钉钉私聊通知测试",
        summary="管理员从 V3 发起的企业应用工作通知测试",
        level="success",
        user_id=user.id,
        user_name=user.name,
        at_user_id=user.dingtalk_user_id or "",
        session_id="admin-dingtalk-work-notice-test",
        task="钉钉私聊通知测试",
        stage="企业应用",
    )
    return {"ok": sent}


@router.post("/dingtalk/test-enterprise-token")
def test_dingtalk_enterprise_token(_: User = Depends(require_admin)):
    token = get_access_token()
    return {"ok": True, "token_prefix": token[:6], "token_length": len(token)}


class DingTalkSyncRequest(BaseModel):
    root_dept_id: int = 1
    create_missing_users: bool = False


@router.post("/dingtalk/sync-users")
def sync_dingtalk_users(
    body: DingTalkSyncRequest,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = sync_dingtalk_org(
        db=db,
        root_dept_id=body.root_dept_id,
        create_missing_users=body.create_missing_users,
    )
    return result.__dict__


@router.get("/dingtalk/sync-logs")
def dingtalk_sync_logs(db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    logs = (
        db.query(DingTalkSyncLog)
        .order_by(DingTalkSyncLog.started_at.desc())
        .limit(50)
        .all()
    )
    return {
        "logs": [
            {
                "id": l.id,
                "status": l.status,
                "root_dept_id": l.root_dept_id,
                "department_count": l.department_count,
                "remote_user_count": l.remote_user_count,
                "matched_count": l.matched_count,
                "created_count": l.created_count,
                "updated_count": l.updated_count,
                "skipped_count": l.skipped_count,
                "error": l.error,
                "started_at": l.started_at,
                "finished_at": l.finished_at,
            }
            for l in logs
        ]
    }


@router.get("/dingtalk/notification-logs")
def dingtalk_notification_logs(db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    logs = (
        db.query(NotificationLog)
        .order_by(NotificationLog.created_at.desc())
        .limit(200)
        .all()
    )
    return {
        "logs": [
            {
                "id": l.id,
                "task": l.task,
                "level": l.level,
                "stage": l.stage,
                "title": l.title,
                "summary": l.summary,
                "user_id": l.user_id,
                "user_name": l.user_name,
                "at_user_id": l.at_user_id,
                "sent": l.sent,
                "skipped_reason": l.skipped_reason,
                "http_status": l.http_status,
                "provider_code": l.provider_code,
                "provider_message": l.provider_message,
                "error": l.error,
                "created_at": l.created_at,
            }
            for l in logs
        ]
    }


@router.post("/users/{user_id}/reset-code")
def reset_code(
    user_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    code = str(1000 + secrets.randbelow(9000))
    user.short_code_hash = hashlib.sha256(code.encode()).hexdigest()
    db.commit()
    return {"short_code": code}


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(
    user_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    now = datetime.now(timezone.utc)
    for sess in user.sessions:
        if not sess.revoked_at:
            sess.revoked_at = now
    db.commit()
    return {"ok": True}


@router.get("/audit-logs")
def audit_logs(db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(200)
        .all()
    )
    return {
        "logs": [
            {
                "id": l.id,
                "user_id": l.user_id,
                "action": l.action,
                "summary": l.summary,
                "ip_address": l.ip_address,
                "created_at": l.created_at,
            }
            for l in logs
        ]
    }
