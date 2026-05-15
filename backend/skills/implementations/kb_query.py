"""知识库查询 — 走志数 (Zhishu/Dify) 后端，整段回答非流式返回。

This skill is selected by the dispatcher when the request carries
`use_kb=True`. It does not rely on intent classification; the dispatcher
short-circuits via `fast_match` looking at SkillContext-style hints.

Note: kb_query is wired through dispatch via use_kb flag, not via classifier
intent. We register it under a unique intent so callers can also force it via
explicit classification, but selection in production is by `use_kb=True`.
"""
from __future__ import annotations

from typing import AsyncIterator

import httpx

from config import AI_HTTP_VERIFY_SSL, ZHISHU_API_KEY, ZHISHU_BASE_URL
from skills.base import SkillContext, done_event


class KbQuerySkill:
    intent = "kb_query"
    description = "（内部）通过知识库回答用户问题——由 use_kb 标志触发，分类器不会选中"
    next_stage: str | None = None

    async def handle(self, ctx: SkillContext) -> AsyncIterator[dict]:
        try:
            async with httpx.AsyncClient(verify=AI_HTTP_VERIFY_SSL, timeout=120) as hc:
                resp = await hc.post(
                    f"{ZHISHU_BASE_URL}/chat-messages",
                    json={
                        "query": ctx.message,
                        "inputs": {},
                        "response_mode": "blocking",
                        "user": "training-manager",
                        "conversation_id": ctx.kb_conversation_id,
                    },
                    headers={
                        "Authorization": f"Bearer {ZHISHU_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                reply = data.get("answer", "（知识库未返回内容）")
                new_conv_id = data.get("conversation_id", "")
        except Exception as e:
            reply = f"❌ 知识库查询失败：{e}"
            new_conv_id = ""

        yield done_event(
            reply=reply,
            next_stage="idle",
            kb_conversation_id=new_conv_id,
        )


SKILL = KbQuerySkill()
