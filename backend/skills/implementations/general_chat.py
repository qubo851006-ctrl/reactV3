"""通用对话 — fallback skill registered under intent='other'.

Streams the LLM reply token-by-token. Carries the classifier's `next_stage`
suggestion through to the frontend (filtered to the actionable allow-list so
hallucinated stages can't slip through).
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from llm_client import format_llm_error
from skills.base import SkillContext, chunk_event, done_event
from skills.registry import ACTIONABLE_STAGES, WORKFLOW_HINTS


def _build_system_prompt() -> str:
    return (
        "你是法务合规部的智能助手，请用中文简洁友好地回答用户问题。\n\n"
        "可以引导用户使用的功能：\n"
        f"{WORKFLOW_HINTS}\n\n"
        "直接输出回复内容，不需要 JSON 格式。"
    )


def _chunk_delta(chunk) -> str | None:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return None
    delta = getattr(choices[0], "delta", None)
    return getattr(delta, "content", None)


class GeneralChatSkill:
    intent = "other"
    description = "（fallback）普通对话或未匹配到具体业务意图时使用"
    next_stage: str | None = None

    async def handle(self, ctx: SkillContext) -> AsyncIterator[dict]:
        suggested = ctx.classification.next_stage or "idle"
        next_stage = suggested if suggested in ACTIONABLE_STAGES else "idle"

        messages = [{"role": "system", "content": _build_system_prompt()}]
        for msg in ctx.history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": ctx.message})

        accumulated = ""
        async with ctx.tracer.span(
            scene="general_chat_stream",
            user_id=ctx.user.id,
            session_id=ctx.session_id,
        ) as span:
            try:
                stream = await ctx.llm_client.chat.completions.create(
                    model=ctx.selected_chat_model,
                    messages=messages,
                    stream=True,
                    max_tokens=500,
                )
                async for raw_chunk in stream:
                    delta = _chunk_delta(raw_chunk)
                    if delta:
                        accumulated += delta
                        yield chunk_event(delta)
                        await asyncio.sleep(0)
            except Exception as e:
                err = format_llm_error(e)
                if accumulated:
                    accumulated += f"\n\n{err}"
                    yield chunk_event(f"\n\n{err}")
                else:
                    accumulated = err
                span.record(
                    model=ctx.selected_chat_model,
                    input_messages=messages,
                    output_text=accumulated,
                    prompt_template_id="general_chat.v1",
                )
                yield done_event(reply="", next_stage="idle")
                return

            span.record(
                model=ctx.selected_chat_model,
                input_messages=messages,
                output_text=accumulated,
                prompt_template_id="general_chat.v1",
            )

        yield done_event(reply="", next_stage=next_stage)
        # The full text was already streamed via chunk events; reply="" tells
        # the dispatcher to persist `accumulated` as the assistant message.


SKILL = GeneralChatSkill()
