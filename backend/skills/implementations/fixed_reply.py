"""Fixed-reply skills.

These skills don't call any external service — they answer with a canned
message and a `next_stage` that tells the frontend what UI to open
(e.g. opening the file uploader for training/ledger flows).

Metadata is still sourced from `skills.registry.WORKFLOW_SKILLS` so adding a
new fixed-reply skill is a single edit to the legacy registry — no class to
write here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

from skills.base import SkillContext, done_event
from skills.registry import WORKFLOW_SKILLS


@dataclass(frozen=True)
class FixedReplySkill:
    intent: str
    description: str
    reply: str
    next_stage: str

    async def handle(self, ctx: SkillContext) -> AsyncIterator[dict]:
        yield done_event(reply=self.reply, next_stage=self.next_stage)


SKILLS: list[FixedReplySkill] = [
    FixedReplySkill(
        intent=ws.intent,
        description=ws.intent_description,
        reply=ws.reply,
        next_stage=ws.stage,
    )
    for ws in WORKFLOW_SKILLS
    if ws.fixed_response and ws.reply
]
