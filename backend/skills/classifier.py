"""
LLM-based intent classifier.

The dispatcher calls `classify(client, message, registry)` once per turn.
The prompt is built from the skill registry's metadata, so adding a new skill
automatically extends the classifier without touching this file.
"""
from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from model_routes import resolve_intent_model
from skills.base import Classification, SkillMeta
from skills.tracer import LLMTracer


_VALID_NEXT_STAGES = {
    "waiting_files",
    "waiting_ledger_files",
    "waiting_auth_file",
    "waiting_compliance_file",
    "waiting_ledger_merge_files",
    "waiting_audit_file",
}


def build_classifier_prompt(skill_metas: list[SkillMeta]) -> str:
    """Compose the classifier system prompt from skill metadata.

    Each skill contributes one line. Skills that need extra fields (e.g.
    `company` for query_company) declare them in `extra_fields` and the
    prompt explains the JSON shape accordingly.
    """
    lines = [
        "你是法务合规部的智能助手意图分析器。只返回 JSON，不要其他内容。",
        "",
        "【可用意图】",
    ]
    for meta in skill_metas:
        if meta.extra_fields:
            extra_json = ", ".join(f'"{f}": ...' for f in meta.extra_fields)
            shape = f'{{"intent": "{meta.intent}", {extra_json}}}'
        else:
            shape = f'{{"intent": "{meta.intent}"}}'
        lines.append(f"- {meta.intent}：{meta.description}")
        lines.append(f"  格式：{shape}")
    lines.append("")
    lines.append('【普通对话】格式：{"intent": "other", "next_stage": null}')
    lines.append(
        "next_stage 可选值（仅当用户有明确操作需求时填入，否则填 null）："
        + " / ".join(sorted(_VALID_NEXT_STAGES))
    )
    return "\n".join(lines)


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) > 1:
            text = parts[1].lstrip("json").strip()
    return text


def _coerce_classification(
    data: dict,
    valid_intents: set[str],
) -> Classification:
    intent = data.get("intent", "other")
    if intent not in valid_intents:
        intent = "other"
    try:
        claim_amount = float(data.get("claim_amount") or 0)
    except (TypeError, ValueError):
        claim_amount = 0.0
    next_stage = data.get("next_stage")
    if next_stage not in _VALID_NEXT_STAGES:
        next_stage = None
    return Classification(
        intent=intent,
        company=data.get("company"),
        claim_amount=claim_amount,
        next_stage=next_stage,
    )


async def classify(
    client: AsyncOpenAI,
    message: str,
    skill_metas: list[SkillMeta],
    *,
    tracer: LLMTracer,
    user_id: int | None = None,
    session_id: str | None = None,
) -> Classification:
    """Run intent classification for one user turn."""
    system_prompt = build_classifier_prompt(skill_metas)
    valid_intents = {meta.intent for meta in skill_metas} | {"other"}
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]
    model = resolve_intent_model()

    async with tracer.span(
        scene="intent_classify",
        user_id=user_id,
        session_id=session_id,
    ) as span:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=80,
            )
        except Exception:
            logging.exception("intent classification failed")
            return Classification(intent="other")

        raw_output = resp.choices[0].message.content or ""
        span.record(
            model=model,
            input_messages=messages,
            output_text=raw_output,
            usage=getattr(resp, "usage", None),
            prompt_template_id="classifier.v1",
        )

    try:
        data = json.loads(_strip_code_fence(raw_output))
    except (json.JSONDecodeError, ValueError):
        return Classification(intent="other")
    return _coerce_classification(data, valid_intents)
