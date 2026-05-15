"""企业查询 — 通过 QCC MCP 拉取工商/司法信息。"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from skills.base import SkillContext, done_event


class QueryCompanySkill:
    intent = "query_company"
    description = "用户提及具体公司名称并想查询工商/司法等基本信息"
    next_stage: str | None = None
    extra_fields: tuple[str, ...] = ("company",)

    async def handle(self, ctx: SkillContext) -> AsyncIterator[dict]:
        company = ctx.classification.company or ctx.message
        try:
            from utils.qcc_mcp_client import (
                query_company as qcc_query,
                format_company_markdown as qcc_format,
            )
            try:
                result = await asyncio.to_thread(qcc_query, company)
                reply = qcc_format(result)
            except Exception:
                from utils.mcp_client import query_company, format_company_markdown
                result = await asyncio.to_thread(query_company, company)
                reply = format_company_markdown(result)
        except ValueError as e:
            reply = f"❌ 未找到匹配企业：{e}"
        except Exception as e:
            reply = f"❌ 企业信息查询失败：{e}"

        yield done_event(reply=reply, next_stage="idle")


SKILL = QueryCompanySkill()
