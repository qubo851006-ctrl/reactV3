# -*- coding: utf-8 -*-
"""
LLM 输出后处理工具。

V3 项目里 LLM 经常被要求"只输出一个短词"（培训类别、文书类型、风险等级
等），但小模型不一定听话，可能吐 Markdown code block / JSON / 解释性
前缀 / 整段输入复述等。这里集中处理这些异常情况，避免单点失效。
"""
from __future__ import annotations

import json
import re
from typing import Iterable

# Markdown code fence 包裹：```json\n...\n```
_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*|\s*```$", re.MULTILINE)

# 常见的解释性前缀
_PREFIX_RE = re.compile(
    r"^(类别|培训类别|分类|结果|答案|类型|文书类型|风险等级|输出)[：:\s]*"
)

# 去掉外层引号和书名号
_QUOTE_CHARS = "\"'“”‘’「」『』【】"


def extract_short_text(
    raw: str | None,
    *,
    max_len: int = 20,
    json_keys: Iterable[str] = ("category", "类别", "分类", "type", "result"),
    fallback: str = "其他",
    whitelist: Iterable[str] | None = None,
) -> str:
    """从 LLM 任意输出里安全提取一个短字符串。

    防御层次：
      1. 剥 markdown code fence
      2. 如果是 JSON 对象，从 json_keys 里依次找候选字段
      3. 去掉"类别:""分类:"等解释性前缀
      4. 去掉外层引号、书名号
      5. 长度兜底（防止整段输入被原样返回）
      6. 可选白名单兜底（确保只在已知值集合内）

    Args:
        raw: LLM 原始返回（可能为 None / 空 / 整段 JSON / 带解释）
        max_len: 超过此长度认为 LLM 跑偏了，回退到 fallback
        json_keys: 如果输出是 JSON，依次尝试的字段名
        fallback: 无法提取时的默认值
        whitelist: 如果给定，提取结果不在白名单里则回退到 fallback

    Returns:
        清理后的短字符串，无法提取时返回 fallback。
    """
    if raw is None:
        return fallback
    text = raw.strip()
    if not text:
        return fallback

    # 1) 剥 markdown code fence
    text = _FENCE_RE.sub("", text).strip()

    # 2) 如果是 JSON 对象，提取关键字段
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                for key in json_keys:
                    cand = obj.get(key)
                    if isinstance(cand, str) and cand.strip():
                        text = cand.strip()
                        break
        except (ValueError, TypeError):
            pass

    # 3) 去掉解释性前缀（可能反复出现，做两遍）
    for _ in range(2):
        new = _PREFIX_RE.sub("", text).strip()
        if new == text:
            break
        text = new

    # 4) 去掉首尾标点和引号
    text = text.replace("：", "").replace(":", "").strip().strip(_QUOTE_CHARS).strip()

    # 5) 长度兜底
    if not text or len(text) > max_len:
        return fallback

    # 6) 白名单兜底
    if whitelist is not None:
        wl = list(whitelist)
        if text not in wl:
            # 包含匹配：LLM 可能输出"合规培训类"，与"合规培训"近似
            for w in wl:
                if w and w in text:
                    return w
            return fallback

    return text
