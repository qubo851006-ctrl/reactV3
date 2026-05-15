"""PersistentTracer — writes one LLMTrace row per LLM call.

Implements skills.tracer.LLMTracer. Skills don't depend on this module
directly; the dispatcher injects it. This means the audit infrastructure can
change (different DB, sampling, async queue) without touching skills.

Failure policy: tracing must never break a user-facing call. All persistence
errors are swallowed and logged. The skill always sees a normal span.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time as _time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Iterator

from db import SessionLocal
from llm_audit.models import LLMTrace
from skills.tracer import TraceSpan


logger = logging.getLogger(__name__)


def _new_trace_id() -> str:
    return secrets.token_hex(12)


def _hash_input(messages: list[dict] | None) -> str:
    if not messages:
        return ""
    canon = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _preview_input(messages: list[dict] | None, limit: int = 500) -> str | None:
    if not messages:
        return None
    user_chunks: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            user_chunks.append(f"[{msg.get('role','?')}] {content}")
    joined = "\n".join(user_chunks)
    return joined[:limit] if joined else None


def _serialise_input(messages: list[dict] | None) -> str | None:
    if not messages:
        return None
    try:
        return json.dumps(messages, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


class PersistentTracer:
    """Writes one LLMTrace row per `span` context exit.

    The span yielded inside the `async with` is the same TraceSpan dataclass
    used by NoopTracer, so call sites are identical. We snapshot timing on
    enter, capture results from the span on exit, and persist atomically.
    """

    def __init__(self, session_factory=SessionLocal):
        self._session_factory = session_factory

    @asynccontextmanager
    async def span(
        self,
        scene: str,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[TraceSpan]:
        span = TraceSpan(scene=scene, user_id=user_id, session_id=session_id)
        trace_id = _new_trace_id()
        started = _time.perf_counter()
        error_text: str | None = None
        try:
            yield span
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"[:500]
            raise
        finally:
            duration_ms = int((_time.perf_counter() - started) * 1000)
            self._safe_persist(trace_id, span, duration_ms, error_text)

    @contextmanager
    def sync_span(
        self,
        scene: str,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
    ) -> Iterator[TraceSpan]:
        """Synchronous variant for utils that aren't async (ledger_helpers,
        compliance_ledger, auth_request_drafter etc)."""
        span = TraceSpan(scene=scene, user_id=user_id, session_id=session_id)
        trace_id = _new_trace_id()
        started = _time.perf_counter()
        error_text: str | None = None
        try:
            yield span
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"[:500]
            raise
        finally:
            duration_ms = int((_time.perf_counter() - started) * 1000)
            self._safe_persist(trace_id, span, duration_ms, error_text)

    def _safe_persist(
        self,
        trace_id: str,
        span: TraceSpan,
        duration_ms: int,
        error_text: str | None,
    ) -> None:
        try:
            self._persist(trace_id, span, duration_ms, error_text)
        except Exception:
            logger.exception("LLM trace persistence failed (trace_id=%s)", trace_id)

    def _persist(
        self,
        trace_id: str,
        span: TraceSpan,
        duration_ms: int,
        error_text: str | None,
    ) -> None:
        row = LLMTrace(
            trace_id=trace_id,
            scene=span.scene,
            prompt_template_id=span.prompt_template_id,
            model=span.model,
            input_hash=_hash_input(span.input_messages),
            input_preview=_preview_input(span.input_messages),
            input_text=_serialise_input(span.input_messages),
            output_text=span.output_text,
            tokens_in=span.tokens_in,
            tokens_out=span.tokens_out,
            duration_ms=duration_ms,
            user_id=span.user_id,
            session_id=span.session_id,
            error=error_text,
            created_at=datetime.now(timezone.utc),
        )
        db = self._session_factory()
        try:
            db.add(row)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
