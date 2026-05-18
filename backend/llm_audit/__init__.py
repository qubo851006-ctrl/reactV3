"""LLM call audit — persistent traces for every LLM call.

Public API:
    # Manual span (full control)
    from llm_audit import get_tracer
    with get_tracer().sync_span("extract_case_fields") as span:
        resp = client.chat.completions.create(...)
        span.record(model=..., input_messages=..., output_text=..., usage=resp.usage)

    # Convenience wrapper (covers 95% of call sites)
    from llm_audit import traced_complete
    resp = traced_complete(
        client,
        scene="extract_case_fields",
        prompt_template_id="ledger.suosostate.v1",
        model="qwen2.5-72b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000, temperature=0.1,
    )

Why a separate package: the audit table will eventually move to PostgreSQL
(P0-1) and may grow query/analytics features. Keeping it isolated from
`models` makes that migration incremental.
"""
from __future__ import annotations

from typing import Any

from skills.tracer import LLMTracer

_tracer: LLMTracer | None = None


def get_tracer() -> LLMTracer:
    """Lazy-initialised singleton — avoids importing PersistentTracer at
    module load time so test code can swap in NoopTracer first.

    If the audit DB isn't reachable, returns a NoopTracer so business calls
    proceed unaffected. The dispatcher already handles tracer failures, so
    this is belt-and-braces.
    """
    global _tracer
    if _tracer is None:
        from llm_audit.db import get_audit_session_factory
        if get_audit_session_factory() is None:
            from skills.tracer import NoopTracer
            _tracer = NoopTracer()
        else:
            from llm_audit.tracer import PersistentTracer
            _tracer = PersistentTracer()
    return _tracer


def set_tracer(tracer: LLMTracer) -> None:
    """Override the singleton (used by tests / scripts)."""
    global _tracer
    _tracer = tracer


def _resolve_messages_with_few_shot(
    messages: list[dict],
    scene: str,
    inject_few_shot: bool,
) -> list[dict]:
    """Optionally prepend a few-shot system prefix sourced from user-accepted
    historical corrections. Vision scenes are auto-skipped (handled inside
    `maybe_inject`)."""
    if not inject_few_shot:
        return messages
    try:
        from llm_audit.few_shot import maybe_inject
        return maybe_inject(messages, scene)
    except Exception:
        # Few-shot is a quality booster, never a correctness requirement.
        import logging
        logging.getLogger(__name__).exception(
            "few-shot injection failed for scene=%s; falling back to raw messages", scene,
        )
        return messages


def _resolve_model_for_scene(scene: str, caller_model: str) -> str:
    """Look up the scene→model routing table. Falls back to caller_model
    when no routing exists (e.g. vision scenes)."""
    try:
        from llm_audit.scene_models import resolve_model
        return resolve_model(scene, caller_model) or caller_model
    except Exception:
        return caller_model


def traced_complete(
    client: Any,
    *,
    scene: str,
    prompt_template_id: str,
    model: str,
    messages: list[dict],
    user_id: int | None = None,
    session_id: str | None = None,
    inject_few_shot: bool = True,
    **completion_kwargs: Any,
):
    """Sync chat completion wrapped in an audit span.

    `inject_few_shot=True` (default) prepends user-accepted examples for the
    same scene as a system prompt. Vision scenes (`vision_*`, `ledger.vision_*`)
    auto-skip injection regardless of this flag.

    `model` is the caller's preferred default — `llm_audit.scene_models`
    can override it per-scene (P1-3 routing). Vision scenes pass through.

    Persistence errors are swallowed by the tracer — this call never raises
    because of tracing. LLM errors propagate normally (and are also captured
    in the trace row's `error` field).
    """
    final_messages = _resolve_messages_with_few_shot(messages, scene, inject_few_shot)
    effective_model = _resolve_model_for_scene(scene, model)
    with get_tracer().sync_span(
        scene=scene, user_id=user_id, session_id=session_id,
    ) as span:
        resp = client.chat.completions.create(
            model=effective_model, messages=final_messages, **completion_kwargs,
        )
        output_text = None
        if getattr(resp, "choices", None):
            try:
                output_text = resp.choices[0].message.content
            except (AttributeError, IndexError):
                output_text = None
        span.record(
            model=effective_model,
            input_messages=final_messages,
            output_text=output_text,
            usage=getattr(resp, "usage", None),
            prompt_template_id=prompt_template_id,
        )
    return resp


async def traced_acomplete(
    async_client: Any,
    *,
    scene: str,
    prompt_template_id: str,
    model: str,
    messages: list[dict],
    user_id: int | None = None,
    session_id: str | None = None,
    inject_few_shot: bool = True,
    **completion_kwargs: Any,
):
    """Async variant of `traced_complete` for AsyncOpenAI call sites."""
    final_messages = _resolve_messages_with_few_shot(messages, scene, inject_few_shot)
    effective_model = _resolve_model_for_scene(scene, model)
    async with get_tracer().span(
        scene=scene, user_id=user_id, session_id=session_id,
    ) as span:
        resp = await async_client.chat.completions.create(
            model=effective_model, messages=final_messages, **completion_kwargs,
        )
        output_text = None
        if getattr(resp, "choices", None):
            try:
                output_text = resp.choices[0].message.content
            except (AttributeError, IndexError):
                output_text = None
        span.record(
            model=effective_model,
            input_messages=final_messages,
            output_text=output_text,
            usage=getattr(resp, "usage", None),
            prompt_template_id=prompt_template_id,
        )
    return resp
