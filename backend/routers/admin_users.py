import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from auth_utils import require_admin
from db import get_db
from models import AuditLog, User, UserSession

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
    db.commit()
    return {"ok": True}


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
