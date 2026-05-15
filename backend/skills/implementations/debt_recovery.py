"""债务清偿评估 — QCC + LLM 综合评估追偿可行性。"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from skills.base import SkillContext, done_event


class DebtRecoverySkill:
    intent = "debt_recovery_assessment"
    description = (
        "用户想评估某企业的偿债能力、追偿可行性、诉前保全决策、债权回收分析等"
    )
    next_stage: str | None = None
    extra_fields: tuple[str, ...] = ("company", "claim_amount")

    async def handle(self, ctx: SkillContext) -> AsyncIterator[dict]:
        company = ctx.classification.company or ctx.message
        claim_amount = ctx.classification.claim_amount or 0.0
        try:
            from utils.qcc_debt_assessment import (
                assess_debt_recovery,
                format_assessment_markdown,
            )
            result = await asyncio.to_thread(
                assess_debt_recovery, company, float(claim_amount)
            )
            reply = format_assessment_markdown(result)
        except Exception as e:
            reply = f"❌ 债务清偿评估失败：{e}"

        yield done_event(reply=reply, next_stage="idle")


SKILL = DebtRecoverySkill()
