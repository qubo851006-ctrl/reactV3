from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    department: Mapped[str] = mapped_column(String(50), default="法务部")
    role: Mapped[str] = mapped_column(String(20), default="user")     # admin | user
    status: Mapped[str] = mapped_column(String(20), default="active") # active | disabled
    dingtalk_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    dingtalk_union_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    dingtalk_dept_ids: Mapped[str | None] = mapped_column(String(300), nullable=True)
    dingtalk_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dingtalk_mobile_tail: Mapped[str | None] = mapped_column(String(8), nullable=True)
    dingtalk_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dingtalk_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    short_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    device_label: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship(back_populates="sessions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    summary: Mapped[str] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User | None"] = relationship(back_populates="audit_logs")


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(30), default="dingtalk")
    task: Mapped[str] = mapped_column(String(80))
    level: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(150))
    summary: Mapped[str] = mapped_column(String(500))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    at_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    skipped_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DingTalkSyncLog(Base):
    __tablename__ = "dingtalk_sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(20))
    root_dept_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department_count: Mapped[int] = mapped_column(Integer, default=0)
    remote_user_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
