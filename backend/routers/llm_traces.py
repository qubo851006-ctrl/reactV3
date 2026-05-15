"""Read-only API over llm_traces — admin debugging + acceptance feedback.

Two endpoints:
- GET  /api/llm-traces             list recent traces with filters
- GET  /api/llm-traces/{trace_id}  full row including input_text/output_text
- POST /api/llm-traces/{trace_id}/feedback   record accepted/edited_to

Access is restricted to admins. The full input/output payloads are large and
may contain sensitive document text — list view returns previews only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session as DBSession

from auth_utils import require_admin
from db import get_db
from llm_audit.models import LLMTrace
from models import User


router = APIRouter(prefix="/api/llm-traces", tags=["llm-traces"])


def _row_to_summary(row: LLMTrace) -> dict[str, Any]:
    return {
        "trace_id": row.trace_id,
        "scene": row.scene,
        "model": row.model,
        "prompt_template_id": row.prompt_template_id,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
        "duration_ms": row.duration_ms,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "input_preview": row.input_preview,
        "accepted": row.accepted,
        "has_error": bool(row.error),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _row_to_detail(row: LLMTrace) -> dict[str, Any]:
    base = _row_to_summary(row)
    base.update({
        "input_text": row.input_text,
        "output_text": row.output_text,
        "input_hash": row.input_hash,
        "edited_to": row.edited_to,
        "error": row.error,
    })
    return base


@router.get("")
def list_traces(
    scene: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    session_id: str | None = Query(default=None),
    has_error: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    stmt = select(LLMTrace).order_by(desc(LLMTrace.created_at))
    if scene:
        stmt = stmt.where(LLMTrace.scene == scene)
    if user_id is not None:
        stmt = stmt.where(LLMTrace.user_id == user_id)
    if session_id:
        stmt = stmt.where(LLMTrace.session_id == session_id)
    if has_error is True:
        stmt = stmt.where(LLMTrace.error.is_not(None))
    elif has_error is False:
        stmt = stmt.where(LLMTrace.error.is_(None))
    stmt = stmt.limit(limit).offset(offset)
    rows = db.execute(stmt).scalars().all()
    return {"traces": [_row_to_summary(r) for r in rows], "limit": limit, "offset": offset}


@router.get("/scenes")
def list_scenes(
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Distinct scene names with call counts — useful for the scene filter."""
    from sqlalchemy import func
    stmt = (
        select(LLMTrace.scene, func.count(LLMTrace.id))
        .group_by(LLMTrace.scene)
        .order_by(desc(func.count(LLMTrace.id)))
    )
    rows = db.execute(stmt).all()
    return {"scenes": [{"scene": s, "count": c} for s, c in rows]}


@router.get("/{trace_id}")
def get_trace(
    trace_id: str,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.execute(
        select(LLMTrace).where(LLMTrace.trace_id == trace_id),
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return _row_to_detail(row)


class FeedbackRequest(BaseModel):
    accepted: bool
    edited_to: str | None = None


@router.post("/{trace_id}/feedback")
def record_feedback(
    trace_id: str,
    body: FeedbackRequest,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Mark whether the user accepted the LLM output, and what they changed
    it to. Powers per-prompt acceptance metrics (P1-2 reflective learning)."""
    row = db.execute(
        select(LLMTrace).where(LLMTrace.trace_id == trace_id),
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="trace not found")
    row.accepted = body.accepted
    row.edited_to = body.edited_to
    db.commit()
    return {"ok": True}
