"""Answer 'what model are you?' without going through LLM classification."""
from __future__ import annotations

import re
from typing import AsyncIterator

from skills.base import SkillContext, done_event


_KEYWORDS = (
    "你是什么模型",
    "当前模型",
    "用的什么模型",
    "模型是什么",
    "现在是什么模型",
)


class ModelStatusSkill:
    intent = "model_status"
    description = "用户询问当前对话使用的模型版本"
    next_stage: str | None = None

    @staticmethod
    def fast_match(message: str) -> bool:
        normalized = re.sub(r"\s+", "", message.lower())
        return any(kw in normalized for kw in _KEYWORDS)

    async def handle(self, ctx: SkillContext) -> AsyncIterator[dict]:
        reply = (
            f"当前文字模型：{ctx.selected_chat_model}\n"
            f"当前图像模型：{ctx.selected_vision_model}"
        )
        yield done_event(reply=reply, next_stage="idle")


SKILL = ModelStatusSkill()
