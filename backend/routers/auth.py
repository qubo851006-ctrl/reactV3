import hashlib
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from auth_utils import SESSION_DAYS, _hash, create_session, get_current_user
from db import get_db
from integrations.dingtalk.enterprise import DingTalkEnterpriseError, get_userinfo_by_code
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


def _dingtalk_sso_enabled() -> bool:
    return (
        os.getenv("DINGTALK_ENTERPRISE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        and os.getenv("DINGTALK_SSO_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    )


def _public_user(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "department": user.department,
        "role": user.role,
    }


def _find_dingtalk_login_user(
    db: DBSession,
    *,
    userid: str,
    unionid: str = "",
    name: str = "",
) -> User | None:
    user = db.query(User).filter(User.dingtalk_user_id == userid).first()
    if user:
        return user
    if unionid:
        user = db.query(User).filter(User.dingtalk_union_id == unionid).first()
        if user:
            return user
    if name:
        matches = db.query(User).filter(User.name == name, User.status == "active").all()
        if len(matches) == 1:
            return matches[0]
    return None


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


@router.get("/dingtalk/config")
def dingtalk_sso_config():
    return {
        "enabled": _dingtalk_sso_enabled(),
        "corp_id": os.getenv("DINGTALK_CORP_ID", "").strip(),
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
        "user": _public_user(user)
    }


class DingTalkSsoRequest(BaseModel):
    code: str


@router.post("/dingtalk/sso")
def dingtalk_sso(
    req: DingTalkSsoRequest,
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
):
    if not _dingtalk_sso_enabled():
        raise HTTPException(status_code=403, detail="钉钉免登未启用")
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="缺少钉钉免登码")
    try:
        info = get_userinfo_by_code(code)
    except DingTalkEnterpriseError as e:
        raise HTTPException(status_code=502, detail=f"钉钉免登校验失败：{e}") from e

    user = _find_dingtalk_login_user(db, userid=info.userid, unionid=info.unionid, name=info.name)
    if not user or user.status != "active":
        raise HTTPException(status_code=403, detail="未找到已绑定的 V3 用户，请联系管理员开通")

    changed = False
    if not user.dingtalk_user_id:
        user.dingtalk_user_id = info.userid
        changed = True
    if info.unionid and not user.dingtalk_union_id:
        user.dingtalk_union_id = info.unionid
        changed = True
    if changed:
        db.commit()

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
    return {"user": _public_user(user), "dingtalk_userid": info.userid}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """返回当前登录用户信息。"""
    return {
        "user": {**_public_user(user), "last_login_at": user.last_login_at}
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
