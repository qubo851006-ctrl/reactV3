"""LLM call audit — persistent traces for every LLM call.

Public API:
    from llm_audit import get_tracer
    with get_tracer().sync_span("extract_case_fields") as span:
        resp = client.chat.completions.create(...)
        span.record(model=..., input_messages=..., output_text=..., usage=resp.usage)

Why a separate package: the audit table will eventually move to PostgreSQL
(P0-1) and may grow query/analytics features. Keeping it isolated from
`models` makes that migration incremental.
"""
from __future__ import annotations

from skills.tracer import LLMTracer

_tracer: LLMTracer | None = None


def get_tracer() -> LLMTracer:
    """Lazy-initialised singleton — avoids importing PersistentTracer at
    module load time so test code can swap in NoopTracer first."""
    global _tracer
    if _tracer is None:
        from llm_audit.tracer import PersistentTracer
        _tracer = PersistentTracer()
    return _tracer


def set_tracer(tracer: LLMTracer) -> None:
    """Override the singleton (used by tests / scripts)."""
    global _tracer
    _tracer = tracer
