from __future__ import annotations

import logging
import os
import time
import json
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_DEFAULT_TIMEOUT_SECONDS = 5.0
_API_BASE = "https://oapi.dingtalk.com"
_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


class DingTalkEnterpriseError(RuntimeError):
    pass


@dataclass
class DingTalkUser:
    userid: str
    name: str
    unionid: str = ""
    department: list[int] | None = None
    title: str = ""
    mobile: str = ""
    active: bool | None = None

    @property
    def mobile_tail(self) -> str:
        return self.mobile[-4:] if self.mobile else ""


@dataclass
class DingTalkAuthUser:
    userid: str
    name: str = ""
    unionid: str = ""
    associated_unionid: str = ""


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def enterprise_enabled() -> bool:
    return _env_flag("DINGTALK_ENTERPRISE_ENABLED", False)


def work_notice_enabled() -> bool:
    return enterprise_enabled() and _env_flag("DINGTALK_WORK_NOTICE_ENABLED", False)


def org_sync_enabled() -> bool:
    return enterprise_enabled() and _env_flag("DINGTALK_ORG_SYNC_ENABLED", False)


def _timeout() -> float:
    return float(os.getenv("DINGTALK_NOTIFY_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT_SECONDS)))


def _require_config(*names: str) -> dict[str, str]:
    values = {name: os.getenv(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise DingTalkEnterpriseError(f"missing config: {', '.join(missing)}")
    return values


def clear_token_cache() -> None:
    _token_cache.update({"token": "", "expires_at": 0.0})


def get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return str(_token_cache["token"])

    cfg = _require_config("DINGTALK_APP_KEY", "DINGTALK_APP_SECRET")
    response = httpx.get(
        f"{_API_BASE}/gettoken",
        params={"appkey": cfg["DINGTALK_APP_KEY"], "appsecret": cfg["DINGTALK_APP_SECRET"]},
        timeout=_timeout(),
    )
    data = response.json()
    if response.status_code < 200 or response.status_code >= 300 or data.get("errcode", 0) != 0:
        raise DingTalkEnterpriseError(f"get access_token failed: {data}")
    token = data.get("access_token", "")
    if not token:
        raise DingTalkEnterpriseError("get access_token failed: empty token")
    expires_in = int(data.get("expires_in", 7200))
    _token_cache.update({"token": token, "expires_at": now + expires_in})
    return token


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = get_access_token()
    response = httpx.post(
        f"{_API_BASE}{path}",
        params={"access_token": token},
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=_timeout(),
    )
    data = response.json()
    if response.status_code < 200 or response.status_code >= 300 or data.get("errcode", 0) != 0:
        raise DingTalkEnterpriseError(f"{path} failed: {data}")
    return data


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    token = get_access_token()
    query = {"access_token": token}
    if params:
        query.update(params)
    response = httpx.get(f"{_API_BASE}{path}", params=query, timeout=_timeout())
    data = response.json()
    if response.status_code < 200 or response.status_code >= 300 or data.get("errcode", 0) != 0:
        raise DingTalkEnterpriseError(f"{path} failed: {data}")
    return data


def send_work_notice(
    *,
    userid: str,
    title: str,
    text: str,
    url: str = "",
) -> dict[str, Any]:
    cfg = _require_config("DINGTALK_AGENT_ID")
    payload: dict[str, Any] = {
        "agent_id": int(cfg["DINGTALK_AGENT_ID"]),
        "userid_list": userid,
        "msg": {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text,
            },
        },
    }
    if url:
        payload["to_all_user"] = False
    return _post("/topapi/message/corpconversation/asyncsend_v2", payload)


def list_sub_department_ids(dept_id: int) -> list[int]:
    data = _get("/topapi/v2/department/listsubid", {"dept_id": dept_id})
    result = data.get("result") or []
    if isinstance(result, dict):
        result = result.get("dept_id_list") or result.get("dept_ids") or result.get("department_ids") or []
    return [int(item) for item in result]


def list_department_userids(dept_id: int) -> list[str]:
    userids: list[str] = []
    cursor = 0
    while True:
        data = _post("/topapi/user/listid", {"dept_id": dept_id, "cursor": cursor, "size": 100})
        result = data.get("result") or {}
        userids.extend(str(uid) for uid in result.get("userid_list") or [])
        if not result.get("has_more"):
            break
        cursor = int(result.get("next_cursor") or 0)
    return userids


def get_user_detail(userid: str) -> DingTalkUser:
    data = _post("/topapi/v2/user/get", {"userid": userid, "language": "zh_CN"})
    result = data.get("result") or {}
    return DingTalkUser(
        userid=str(result.get("userid") or userid),
        name=str(result.get("name") or ""),
        unionid=str(result.get("unionid") or ""),
        department=[int(d) for d in (result.get("dept_id_list") or result.get("department") or [])],
        title=str(result.get("title") or ""),
        mobile=str(result.get("mobile") or ""),
        active=result.get("active"),
    )


def get_userinfo_by_code(code: str) -> DingTalkAuthUser:
    data = _post("/topapi/v2/user/getuserinfo", {"code": code})
    result = data.get("result") or {}
    userid = str(result.get("userid") or "")
    if not userid:
        raise DingTalkEnterpriseError("getuserinfo failed: empty userid")
    return DingTalkAuthUser(
        userid=userid,
        name=str(result.get("name") or ""),
        unionid=str(result.get("unionid") or ""),
        associated_unionid=str(result.get("associated_unionid") or ""),
    )


def fetch_org_users(root_dept_id: int = 1) -> tuple[list[int], list[DingTalkUser]]:
    seen_depts: set[int] = set()
    seen_users: set[str] = set()
    departments: list[int] = []
    users: list[DingTalkUser] = []

    def walk(dept_id: int) -> None:
        if dept_id in seen_depts:
            return
        seen_depts.add(dept_id)
        departments.append(dept_id)
        for userid in list_department_userids(dept_id):
            if userid not in seen_users:
                seen_users.add(userid)
                users.append(get_user_detail(userid))
        for child_id in list_sub_department_ids(dept_id):
            walk(child_id)

    walk(root_dept_id)
    return departments, users
