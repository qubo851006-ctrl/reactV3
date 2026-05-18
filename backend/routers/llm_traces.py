"""API over llm_traces — admin debugging, scene stats, and acceptance feedback.

Endpoints:
- GET  /api/llm-traces                       list recent traces with filters (admin)
- GET  /api/llm-traces/scenes                distinct scenes + counts (admin)
- GET  /api/llm-traces/scenes/stats          per-scene acceptance/edit/token stats (admin)
- GET  /api/llm-traces/{trace_id}            full row (admin)
- POST /api/llm-traces/{trace_id}/feedback   record accepted/edited_to (any logged-in user)

The feedback endpoint is NOT admin-only: any user reviewing an extraction
needs to be able to record whether they kept it. Authorization at the
trace level (`user_id` matches caller) is enforced server-side.

All queries hit the audit DB (PostgreSQL since P0-1), not the main SQLite.
The `db` dependency is kept on admin endpoints purely so the auth chain
runs; the actual reads use the audit session factory.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from auth_utils import get_current_user, require_admin
from llm_audit.db import get_audit_session_factory
from llm_audit.models import LLMTrace
from models import User


router = APIRouter(prefix="/api/llm-traces", tags=["llm-traces"])


@contextmanager
def _audit_session():
    factory = get_audit_session_factory()
    if factory is None:
        raise HTTPException(
            status_code=503,
            detail="LLM audit database is not configured or unreachable",
        )
    s = factory()
    try:
        yield s
    finally:
        s.close()


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
    with _audit_session() as s:
        rows = s.execute(stmt).scalars().all()
        return {"traces": [_row_to_summary(r) for r in rows], "limit": limit, "offset": offset}


@router.get("/scenes")
def list_scenes(
    _: User = Depends(require_admin),
):
    """Distinct scene names with call counts — drives the scene filter dropdown."""
    from sqlalchemy import func
    with _audit_session() as s:
        rows = s.execute(
            select(LLMTrace.scene, func.count(LLMTrace.id))
            .group_by(LLMTrace.scene)
            .order_by(desc(func.count(LLMTrace.id)))
        ).all()
    return {"scenes": [{"scene": sc, "count": c} for sc, c in rows]}


@router.get("/scenes/stats")
def scenes_stats(
    _: User = Depends(require_admin),
):
    """Per-scene quality metrics: total calls, acceptance rate, edit rate,
    average tokens, average latency. Drives the admin dashboard.

    Definitions:
    - accepted_count: rows with accepted=True (user kept the result)
    - edited_count:   rows with edited_to NOT NULL (user changed something)
    - rates are computed only over rows that have feedback (accepted IS NOT
      NULL); rows without feedback are excluded to avoid penalising prompts
      whose users haven't reviewed yet.
    """
    from sqlalchemy import case, func
    accepted_expr = case((LLMTrace.accepted.is_(True), 1), else_=0)
    edited_expr = case((LLMTrace.edited_to.is_not(None), 1), else_=0)
    feedback_expr = case((LLMTrace.accepted.is_not(None), 1), else_=0)
    error_expr = case((LLMTrace.error.is_not(None), 1), else_=0)
    with _audit_session() as s:
        rows = s.execute(
            select(
                LLMTrace.scene,
                func.count(LLMTrace.id).label("total"),
                func.sum(feedback_expr).label("feedback"),
                func.sum(accepted_expr).label("accepted"),
                func.sum(edited_expr).label("edited"),
                func.sum(error_expr).label("errors"),
                func.avg(LLMTrace.tokens_in).label("avg_in"),
                func.avg(LLMTrace.tokens_out).label("avg_out"),
                func.avg(LLMTrace.duration_ms).label("avg_ms"),
            )
            .group_by(LLMTrace.scene)
            .order_by(desc(func.count(LLMTrace.id)))
        ).all()
    out = []
    for r in rows:
        total = r.total or 0
        feedback = r.feedback or 0
        accepted = r.accepted or 0
        edited = r.edited or 0
        out.append({
            "scene": r.scene,
            "total": total,
            "feedback_count": feedback,
            "accepted_count": accepted,
            "edited_count": edited,
            "error_count": r.errors or 0,
            "acceptance_rate": (accepted / feedback) if feedback else None,
            "edit_rate": (edited / feedback) if feedback else None,
            "avg_tokens_in": float(r.avg_in or 0),
            "avg_tokens_out": float(r.avg_out or 0),
            "avg_duration_ms": float(r.avg_ms or 0),
        })
    return {"scenes": out}


@router.get("/{trace_id}")
def get_trace(
    trace_id: str,
    _: User = Depends(require_admin),
):
    with _audit_session() as s:
        row = s.execute(
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
    user: User = Depends(get_current_user),
):
    """Mark whether the user accepted the LLM output, and what they changed
    it to. Drives few-shot example selection (see llm_audit.few_shot).

    Authorization: any logged-in user may submit feedback, but only on a
    trace they themselves spawned (row.user_id matches caller). Admins
    bypass the ownership check.
    """
    with _audit_session() as s:
        row = s.execute(
            select(LLMTrace).where(LLMTrace.trace_id == trace_id),
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="trace not found")
        if user.role != "admin" and row.user_id is not None and row.user_id != user.id:
            raise HTTPException(status_code=403, detail="not your trace")
        row.accepted = body.accepted
        row.edited_to = body.edited_to
        scene = row.scene  # capture before commit/session close
        s.commit()
    # Drop the few-shot cache for this scene so the new correction can
    # influence the very next LLM call, not 60 seconds from now.
    try:
        from llm_audit.few_shot import invalidate_cache
        invalidate_cache(scene)
    except Exception:
        pass  # cache invalidation is best-effort
    return {"ok": True}
