"""
LLM call tracer interface.

This module ships a no-op implementation today. The real implementation is
delivered in P0-2 (LLM audit) and will:
- persist every call to a `llm_traces` table
- record scene, model, prompt template id, input hash, output, token usage,
  duration, user/session
- expose hooks for "user accepted" / "user edited to" follow-ups so we can
  measure per-prompt acceptance rates

Skills always go through this interface — they never see whether tracing is
on or off. Switching the real tracer in is a one-line change in dispatcher.

Usage from inside a skill:

    async with ctx.tracer.span(scene="extract_case_fields") as span:
        resp = await ctx.llm_client.chat.completions.create(...)
        span.record(model=ctx.selected_chat_model,
                    input_messages=messages,
                    output_text=resp.choices[0].message.content,
                    usage=resp.usage)
    return resp
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol


@dataclass
class TraceSpan:
    """Mutable handle a skill writes into during one LLM call.

    The Noop implementation accepts everything and discards. The real
    implementation persists on context exit.
    """
    scene: str
    user_id: int | None = None
    session_id: str | None = None
    model: str | None = None
    prompt_template_id: str | None = None
    input_messages: list[dict] | None = None
    output_text: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def record(
        self,
        *,
        model: str | None = None,
        input_messages: list[dict] | None = None,
        output_text: str | None = None,
        usage: Any = None,
        prompt_template_id: str | None = None,
        **extra: Any,
    ) -> None:
        """Record call details. Safe to call multiple times — last wins."""
        if model is not None:
            self.model = model
        if input_messages is not None:
            self.input_messages = input_messages
        if output_text is not None:
            self.output_text = output_text
        if prompt_template_id is not None:
            self.prompt_template_id = prompt_template_id
        if usage is not None:
            self.tokens_in = getattr(usage, "prompt_tokens", 0) or 0
            self.tokens_out = getattr(usage, "completion_tokens", 0) or 0
        if extra:
            self.extra.update(extra)


class LLMTracer(Protocol):
    """Tracer contract. P0-2 ships the persistent implementation."""

    def span(
        self,
        scene: str,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
    ) -> "AsyncIterator[TraceSpan]":
        ...


class NoopTracer:
    """Default tracer used until P0-2 lands. Discards everything."""

    @asynccontextmanager
    async def span(
        self,
        scene: str,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[TraceSpan]:
        yield TraceSpan(scene=scene, user_id=user_id, session_id=session_id)


# Module-level default; dispatcher picks this up unless overridden.
DEFAULT_TRACER: LLMTracer = NoopTracer()
