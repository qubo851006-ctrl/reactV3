import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from db import get_db
from models import User, UserSession

SESSION_DAYS = 30
_COOKIE = "sid"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: DBSession, user: User, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    ua = (request.headers.get("user-agent") or "")[:120]
    sess = UserSession(
        user_id=user.id,
        token_hash=_hash(token),
        device_label=ua,
        expires_at=expires,
    )
    db.add(sess)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return token


def get_current_user(
    request: Request,
    db: DBSession = Depends(get_db),
    sid: str | None = Cookie(default=None),
) -> User:
    if not sid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    now = datetime.now(timezone.utc)
    sess = db.query(UserSession).filter_by(token_hash=_hash(sid)).first()
    if not sess or sess.revoked_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    expires = sess.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    user = sess.user
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被停用")
    sess.last_seen_at = now
    db.commit()
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user
