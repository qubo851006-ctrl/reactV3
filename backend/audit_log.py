from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.orm import Session as DBSession

from models import AuditLog, User


def write_log(
    db: DBSession,
    user: User,
    action: str,
    summary: str,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> None:
    ip = None
    if request and request.client:
        ip = request.client.host
    log = AuditLog(
        user_id=user.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        ip_address=ip,
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()
