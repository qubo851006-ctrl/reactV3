"""SQLAlchemy model for LLM call audit traces.

Lives in the same metadata as the rest of the app (db.Base) so the existing
init_db / create_all flow picks it up. When P0-1 migrates to PostgreSQL we
can move just this table to its own engine without touching consumers.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LLMTrace(Base):
    """One row per LLM completion call.

    Fields are roughly ordered: identity → I/O → cost → context → outcome.

    `input_text` stores the full serialized message list as JSON; preview is
    the user-facing first 500 chars to keep list views cheap. `input_hash`
    enables dedup queries ("how often have we run this exact prompt?").
    """

    __tablename__ = "llm_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    # ── Routing ───────────────────────────────────────────────────────
    scene: Mapped[str] = mapped_column(String(64), index=True)
    """Logical scene, e.g. 'intent_classify', 'extract_case_fields',
    'judgment_summary'. One scene per logical prompt template."""

    prompt_template_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )
    """Versioned id like 'classifier.v1' for tracking prompt iterations."""

    model: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # ── I/O ───────────────────────────────────────────────────────────
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    """SHA-256 of canonicalised input — enables dedup analytics."""

    input_preview: Mapped[str | None] = mapped_column(String(500), nullable=True)
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Full serialised messages JSON. Optional so we can null it out for
    retention purposes without losing the rest of the row."""

    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Cost ──────────────────────────────────────────────────────────
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    # ── Context ───────────────────────────────────────────────────────
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )

    # ── Outcome (filled by follow-up endpoint after user accepts/edits)
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    edited_to: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Errors ────────────────────────────────────────────────────────
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, index=True,
    )
