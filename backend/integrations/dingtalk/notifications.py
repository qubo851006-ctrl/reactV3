from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urlencode, urlsplit, urlunsplit, parse_qsl

import httpx

from .enterprise import DingTalkEnterpriseError, send_work_notice, work_notice_enabled

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_DEFAULT_TIMEOUT_SECONDS = 2.0


def _env_enabled() -> bool:
    return os.getenv("DINGTALK_NOTIFY_ENABLED", "false").strip().lower() in _TRUE_VALUES


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _level_enabled(level: str) -> bool:
    if level == "success":
        return _env_flag("DINGTALK_NOTIFY_ON_SUCCESS", True)
    if level == "error":
        return _env_flag("DINGTALK_NOTIFY_ON_FAILURE", True)
    if level == "warning":
        return _env_flag("DINGTALK_NOTIFY_ON_WARNING", True)
    return True


def _signed_webhook_url(webhook_url: str, secret: str, timestamp: int | None = None) -> str:
    timestamp = timestamp if timestamp is not None else int(time.time() * 1000)
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(digest).decode("utf-8")

    parts = urlsplit(webhook_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["timestamp"] = str(timestamp)
    query["sign"] = sign
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _build_task_url(base_url: str, session_id: str = "") -> str:
    base = base_url.rstrip("/") or "https://192.168.9.226:8443"
    if not session_id:
        return base
    return f"{base}/?session_id={quote_plus(session_id)}"


def _markdown_payload(
    *,
    title: str,
    summary: str,
    level: str,
    user_name: str = "",
    at_user_id: str = "",
    session_id: str = "",
    base_url: str = "",
    stage: str = "",
) -> dict[str, Any]:
    status = {
        "success": "完成",
        "error": "失败",
        "warning": "提醒",
    }.get(level, "通知")
    task_url = _build_task_url(base_url or os.getenv("DINGTALK_NOTIFY_BASE_URL", ""), session_id)
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    at_line = f"\n\n@{at_user_id}" if at_user_id else ""
    lines = [f"- 状态：{status}"]
    if user_name:
        lines.append(f"- 发起人：{user_name}")
    if stage:
        lines.append(f"- 阶段：{stage}")
    lines.extend([
        f"- 摘要：{summary}",
        f"- 时间：{timestamp}",
        f"- 链接：[打开 V3]({task_url})",
    ])
    text = (
        f"### {title}\n\n"
        + "\n".join(lines)
        + at_line
    )
    payload: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text,
        },
    }
    if at_user_id:
        payload["at"] = {
            "atUserIds": [at_user_id],
            "isAtAll": False,
        }
    return payload


def _markdown_text(
    *,
    title: str,
    summary: str,
    level: str,
    user_name: str = "",
    session_id: str = "",
    stage: str = "",
) -> str:
    return _markdown_payload(
        title=title,
        summary=summary,
        level=level,
        user_name=user_name,
        session_id=session_id,
        stage=stage,
    )["markdown"]["text"]


def _record_notification_log(
    *,
    channel: str = "dingtalk",
    task: str,
    title: str,
    summary: str,
    level: str,
    stage: str = "",
    user_id: int | None = None,
    user_name: str = "",
    at_user_id: str = "",
    sent: bool = False,
    skipped_reason: str = "",
    http_status: int | None = None,
    provider_code: str = "",
    provider_message: str = "",
    error: str = "",
) -> None:
    try:
        from db import SessionLocal
        from models import NotificationLog

        db = SessionLocal()
        try:
            db.add(NotificationLog(
                channel=channel,
                task=task or title,
                level=level,
                stage=stage or None,
                title=title[:150],
                summary=summary[:500],
                user_id=user_id,
                user_name=user_name or None,
                at_user_id=at_user_id or None,
                sent=sent,
                skipped_reason=skipped_reason or None,
                http_status=http_status,
                provider_code=str(provider_code)[:50] if provider_code != "" else None,
                provider_message=str(provider_message)[:300] if provider_message else None,
                error=str(error)[:500] if error else None,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.debug("dingtalk notification log failed", exc_info=True)


def send_dingtalk_notification(
    *,
    title: str,
    summary: str,
    level: str = "success",
    user_name: str = "",
    user_id: int | None = None,
    at_user_id: str = "",
    session_id: str = "",
    task: str = "",
    stage: str = "",
) -> bool:
    """Best-effort DingTalk notification.

    Returns True only when DingTalk accepts at least one channel. Any configuration,
    network, or response error is logged and swallowed so business flows do not
    depend on DingTalk availability.
    """
    if not _env_enabled():
        _record_notification_log(
            task=task,
            title=title,
            summary=summary,
            level=level,
            stage=stage,
            user_id=user_id,
            user_name=user_name,
            at_user_id=at_user_id,
            skipped_reason="disabled",
        )
        return False
    if not _level_enabled(level):
        _record_notification_log(
            task=task,
            title=title,
            summary=summary,
            level=level,
            stage=stage,
            user_id=user_id,
            user_name=user_name,
            at_user_id=at_user_id,
            skipped_reason=f"{level}_disabled",
        )
        return False

    sent_any = False
    # at_user_id can be None when the user has no dingtalk_user_id bound — guard
    # here so a missing binding never breaks the (best-effort) notification path.
    enterprise_userid = (at_user_id or "").strip()
    if enterprise_userid and work_notice_enabled():
        try:
            task_url = _build_task_url(os.getenv("DINGTALK_NOTIFY_BASE_URL", ""), session_id)
            result = send_work_notice(
                userid=enterprise_userid,
                title=title,
                text=_markdown_text(
                    title=title,
                    summary=summary,
                    level=level,
                    user_name=user_name,
                    session_id=session_id,
                    stage=stage,
                ),
                url=task_url,
            )
            _record_notification_log(
                channel="dingtalk_work_notice",
                task=task,
                title=title,
                summary=summary,
                level=level,
                stage=stage,
                user_id=user_id,
                user_name=user_name,
                at_user_id=enterprise_userid,
                sent=True,
                http_status=200,
                provider_code=result.get("errcode", ""),
                provider_message=result.get("errmsg", ""),
            )
            sent_any = True
        except DingTalkEnterpriseError as e:
            logger.warning("dingtalk work notice failed: %s", e)
            _record_notification_log(
                channel="dingtalk_work_notice",
                task=task,
                title=title,
                summary=summary,
                level=level,
                stage=stage,
                user_id=user_id,
                user_name=user_name,
                at_user_id=enterprise_userid,
                error=str(e),
            )
        except Exception as e:
            logger.exception("dingtalk work notice failed")
            _record_notification_log(
                channel="dingtalk_work_notice",
                task=task,
                title=title,
                summary=summary,
                level=level,
                stage=stage,
                user_id=user_id,
                user_name=user_name,
                at_user_id=enterprise_userid,
                error=str(e),
            )

    webhook_url = os.getenv("DINGTALK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        if sent_any:
            return True
        _record_notification_log(
            task=task,
            title=title,
            summary=summary,
            level=level,
            stage=stage,
            user_id=user_id,
            user_name=user_name,
            at_user_id=at_user_id,
            skipped_reason="missing_webhook",
        )
        return False

    secret = os.getenv("DINGTALK_WEBHOOK_SECRET", "").strip()
    url = _signed_webhook_url(webhook_url, secret) if secret else webhook_url
    timeout = float(os.getenv("DINGTALK_NOTIFY_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT_SECONDS)))
    effective_at_user_id = at_user_id if _env_flag("DINGTALK_NOTIFY_MENTION_USER", True) else ""
    payload = _markdown_payload(
        title=title,
        summary=summary,
        level=level,
        user_name=user_name,
        at_user_id=effective_at_user_id,
        session_id=session_id,
        stage=stage,
    )

    try:
        response = httpx.post(
            url,
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=timeout,
        )
        if response.status_code < 200 or response.status_code >= 300:
            logger.warning("dingtalk notify http status=%s body=%s", response.status_code, response.text[:500])
            _record_notification_log(
                task=task,
                title=title,
                summary=summary,
                level=level,
                stage=stage,
                user_id=user_id,
                user_name=user_name,
                at_user_id=effective_at_user_id,
                http_status=response.status_code,
                error=response.text[:500],
            )
            return sent_any
        data = response.json()
        if data.get("errcode", 0) != 0:
            logger.warning("dingtalk notify rejected: %s", data)
            _record_notification_log(
                task=task,
                title=title,
                summary=summary,
                level=level,
                stage=stage,
                user_id=user_id,
                user_name=user_name,
                at_user_id=effective_at_user_id,
                http_status=response.status_code,
                provider_code=data.get("errcode", ""),
                provider_message=data.get("errmsg", ""),
            )
            return sent_any
        _record_notification_log(
            task=task,
            title=title,
            summary=summary,
            level=level,
            stage=stage,
            user_id=user_id,
            user_name=user_name,
            at_user_id=effective_at_user_id,
            sent=True,
            http_status=response.status_code,
            provider_code=data.get("errcode", ""),
            provider_message=data.get("errmsg", ""),
        )
        return True
    except Exception as e:
        logger.exception("dingtalk notify failed")
        _record_notification_log(
            task=task,
            title=title,
            summary=summary,
            level=level,
            stage=stage,
            user_id=user_id,
            user_name=user_name,
            at_user_id=effective_at_user_id,
            error=str(e),
        )
        return sent_any


def _user_id(user: Any | None) -> int | None:
    return getattr(user, "id", None) if user is not None else None


def notify_task_success(
    *,
    task: str,
    summary: str,
    user: Any | None = None,
    session_id: str = "",
    stage: str = "",
) -> bool:
    return send_dingtalk_notification(
        title=f"{task}完成",
        summary=summary,
        level="success",
        task=task,
        stage=stage,
        user_id=_user_id(user),
        user_name=getattr(user, "name", "") if user is not None else "",
        at_user_id=(getattr(user, "dingtalk_user_id", "") or "") if user is not None else "",
        session_id=session_id,
    )


def notify_task_failure(
    *,
    task: str,
    summary: str,
    user: Any | None = None,
    session_id: str = "",
    stage: str = "",
) -> bool:
    return send_dingtalk_notification(
        title=f"{task}失败",
        summary=summary,
        level="error",
        task=task,
        stage=stage,
        user_id=_user_id(user),
        user_name=getattr(user, "name", "") if user is not None else "",
        at_user_id=(getattr(user, "dingtalk_user_id", "") or "") if user is not None else "",
        session_id=session_id,
    )


def notify_task_warning(
    *,
    task: str,
    summary: str,
    user: Any | None = None,
    session_id: str = "",
    stage: str = "需要人工确认",
) -> bool:
    return send_dingtalk_notification(
        title=f"{task}需要人工确认",
        summary=summary,
        level="warning",
        task=task,
        stage=stage,
        user_id=_user_id(user),
        user_name=getattr(user, "name", "") if user is not None else "",
        at_user_id=(getattr(user, "dingtalk_user_id", "") or "") if user is not None else "",
        session_id=session_id,
    )
