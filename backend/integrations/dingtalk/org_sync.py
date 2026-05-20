from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import DingTalkSyncLog, User

from .enterprise import DingTalkEnterpriseError, DingTalkUser, fetch_org_users, org_sync_enabled


@dataclass
class DingTalkSyncResult:
    status: str
    root_dept_id: int
    department_count: int = 0
    remote_user_count: int = 0
    matched_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    error: str = ""


def _dept_ids_text(user: DingTalkUser) -> str:
    return ",".join(str(dept_id) for dept_id in (user.department or []))


def _find_v3_user(db: Session, remote: DingTalkUser) -> User | None:
    existing = db.query(User).filter(User.dingtalk_user_id == remote.userid).first()
    if existing:
        return existing
    if remote.unionid:
        existing = db.query(User).filter(User.dingtalk_union_id == remote.unionid).first()
        if existing:
            return existing
    if remote.name:
        return db.query(User).filter(User.name == remote.name).first()
    return None


def _apply_dingtalk_fields(user: User, remote: DingTalkUser, now: datetime) -> bool:
    changed = False
    updates = {
        "dingtalk_user_id": remote.userid,
        "dingtalk_union_id": remote.unionid or None,
        "dingtalk_dept_ids": _dept_ids_text(remote) or None,
        "dingtalk_title": remote.title or None,
        "dingtalk_mobile_tail": remote.mobile_tail or None,
        "dingtalk_active": remote.active,
        "dingtalk_synced_at": now,
    }
    for field, value in updates.items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed = True
    return changed


def sync_dingtalk_org(
    *,
    db: Session,
    root_dept_id: int = 1,
    create_missing_users: bool = False,
) -> DingTalkSyncResult:
    if not org_sync_enabled():
        return DingTalkSyncResult(status="disabled", root_dept_id=root_dept_id)

    log = DingTalkSyncLog(status="running", root_dept_id=str(root_dept_id))
    db.add(log)
    db.commit()
    db.refresh(log)

    result = DingTalkSyncResult(status="ok", root_dept_id=root_dept_id)
    now = datetime.now(timezone.utc)
    try:
        departments, remote_users = fetch_org_users(root_dept_id)
        result.department_count = len(departments)
        result.remote_user_count = len(remote_users)

        for remote in remote_users:
            existing = _find_v3_user(db, remote)
            if existing:
                result.matched_count += 1
                if _apply_dingtalk_fields(existing, remote, now):
                    result.updated_count += 1
                continue

            if not create_missing_users:
                result.skipped_count += 1
                continue

            code = str(1000 + secrets.randbelow(9000))
            user = User(
                name=remote.name.strip() or remote.userid,
                department="钉钉同步",
                role="user",
                status="active",
                short_code_hash=hashlib.sha256(code.encode()).hexdigest(),
            )
            _apply_dingtalk_fields(user, remote, now)
            db.add(user)
            result.created_count += 1

        log.status = "ok"
        log.department_count = result.department_count
        log.remote_user_count = result.remote_user_count
        log.matched_count = result.matched_count
        log.created_count = result.created_count
        log.updated_count = result.updated_count
        log.skipped_count = result.skipped_count
        log.finished_at = datetime.now(timezone.utc)
        db.commit()
        return result
    except DingTalkEnterpriseError as e:
        result.status = "error"
        result.error = str(e)
        log.status = "error"
        log.error = result.error[:500]
        log.finished_at = datetime.now(timezone.utc)
        db.commit()
        return result
    except Exception as e:
        result.status = "error"
        result.error = str(e)
        log.status = "error"
        log.error = result.error[:500]
        log.finished_at = datetime.now(timezone.utc)
        db.commit()
        return result
