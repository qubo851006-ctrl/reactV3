"""Per-request collection of trace_ids spawned during one business operation.

Why: a single user action (e.g. uploading 3 legal documents) triggers
multiple traced LLM calls. The HTTP response needs to ship back the list of
trace_ids so the frontend can later send feedback (accepted / edited_to)
referencing each one.

Using contextvars instead of threading a trace_id through every function
keeps the business code (ledger_helpers, compliance_ledger, …) untouched
and works correctly under asyncio + thread offloading because contextvars
propagate across `asyncio.to_thread` boundaries (PEP 568).

Usage:

    from llm_audit.context import collect_traces

    with collect_traces() as bucket:
        case = extract_case_fields(docs)          # multiple LLM calls inside
    trace_ids = bucket.ids                        # ['abc123', 'def456', …]

    # Later, return trace_ids alongside the business payload so the
    # frontend can attach feedback.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator


_BUCKET: ContextVar["TraceBucket | None"] = ContextVar(
    "llm_audit.trace_bucket", default=None,
)


@dataclass
class TraceBucket:
    ids: list[str] = field(default_factory=list)

    def add(self, trace_id: str) -> None:
        self.ids.append(trace_id)


def current_bucket() -> TraceBucket | None:
    """Return the active bucket, or None if no `collect_traces` is in scope."""
    return _BUCKET.get()


def record_trace_id(trace_id: str) -> None:
    """Append `trace_id` to the active bucket (no-op if none is active).

    Called by PersistentTracer right after it allocates an id. Safe to call
    from sync or async code — contextvars work in both.
    """
    bucket = _BUCKET.get()
    if bucket is not None:
        bucket.add(trace_id)


@contextmanager
def collect_traces() -> Iterator[TraceBucket]:
    """Open a scope that captures every trace_id produced inside it.

    Nesting is supported but inner scopes shadow outer ones — the parent
    bucket will NOT see ids written inside a nested scope. This matches
    intuition: each `with collect_traces()` is its own atomic operation.
    """
    bucket = TraceBucket()
    token = _BUCKET.set(bucket)
    try:
        yield bucket
    finally:
        _BUCKET.reset(token)
