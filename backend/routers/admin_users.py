import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from auth_utils import require_admin
from db import get_db
from integrations.dingtalk import send_dingtalk_notification
from integrations.dingtalk.enterprise import get_access_token
from integrations.dingtalk.org_sync import sync_dingtalk_org
from models import AuditLog, DingTalkSyncLog, NotificationLog, User, UserSession

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _active_sessions(u: User) -> int:
    now = datetime.now(timezone.utc)
    return sum(
        1
        for s in u.sessions
        if not s.revoked_at
        and (s.expires_at.replace(tzinfo=timezone.utc) if s.expires_at.tzinfo is None else s.expires_at) > now
    )


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
