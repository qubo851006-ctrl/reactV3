import hashlib
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from auth_utils import SESSION_DAYS, _hash, create_session, get_current_user
from db import get_db
from models import User, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", str(10 * 60)))
_LOGIN_FAILURES: dict[tuple[int, str], list[datetime]] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "")


def _login_key(user_id: int, request: Request | str) -> tuple[int, str]:
    ip = request if isinstance(request, str) else _client_ip(request)
    return user_id, ip


def _recent_failures(key: tuple[int, str]) -> list[datetime]:
    cutoff = _utcnow().timestamp() - LOGIN_WINDOW_SECONDS
    failures = [ts for ts in _LOGIN_FAILURES.get(key, []) if ts.timestamp() >= cutoff]
    if failures:
        _LOGIN_FAILURES[key] = failures
    else:
        _LOGIN_FAILURES.pop(key, None)
    return failures


def _login_is_limited(user_id: int, request: Request | str) -> bool:
    return len(_recent_failures(_login_key(user_id, request))) >= LOGIN_MAX_FAILURES


def _record_login_failure(user_id: int, request: Request | str) -> None:
    key = _login_key(user_id, request)
    failures = _recent_failures(key)
    failures.append(_utcnow())
    _LOGIN_FAILURES[key] = failures


def _clear_login_failures(user_id: int, request: Request | str) -> None:
    _LOGIN_FAILURES.pop(_login_key(user_id, request), None)


def _cookie_secure_enabled() -> bool:
    return os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}


@router.get("/users-lite")
def users_lite(db: DBSession = Depends(get_db)):
    """公开接口：返回启用用户列表，供登录页选择姓名。"""
    users = db.query(User).filter_by(status="active").order_by(User.name).all()
    return {
        "users": [
            {"id": u.id, "name": u.name, "department": u.department}
            for u in users
        ]
    }


class BindRequest(BaseModel):
    user_id: int
    short_code: str


@router.post("/bind-device")
def bind_device(
    req: BindRequest,
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
):
    """首次短码验证，成功后写入 HttpOnly Cookie。"""
    user = db.get(User, req.user_id)
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="姓名或短码不正确")
    if _login_is_limited(user.id, request):
        raise HTTPException(status_code=429, detail="短码错误次数过多，请稍后再试")
    code_hash = hashlib.sha256(req.short_code.strip().encode()).hexdigest()
    if not user.short_code_hash or user.short_code_hash != code_hash:
        _record_login_failure(user.id, request)
        raise HTTPException(status_code=401, detail="姓名或短码不正确")

    _clear_login_failures(user.id, request)
    token = create_session(db, user, request)
    response.set_cookie(
        key="sid",
        value=token,
        httponly=True,
        secure=_cookie_secure_enabled(),
        samesite="lax",
        max_age=SESSION_DAYS * 24 * 3600,
        path="/",
    )
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "department": user.department,
            "role": user.role,
        }
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """返回当前登录用户信息。"""
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "department": user.department,
            "role": user.role,
            "last_login_at": user.last_login_at,
        }
    }


@router.post("/logout")
def logout(
    response: Response,
    db: DBSession = Depends(get_db),
    sid: str | None = Cookie(default=None),
):
    """吊销当前会话，清除 Cookie。"""
    if sid:
        sess = db.query(UserSession).filter_by(token_hash=_hash(sid)).first()
        if sess:
            sess.revoked_at = datetime.now(timezone.utc)
            db.commit()
    response.delete_cookie("sid", path="/")
    return {"ok": True}
