# -*- coding: utf-8 -*-
"""
LLM 输出后处理工具。

V3 项目里 LLM 经常被要求"只输出一个短词"（培训类别、文书类型、风险等级
等），但小模型不一定听话，可能吐 Markdown code block / JSON / 解释性
前缀 / 整段输入复述等。这里集中处理这些异常情况，避免单点失效。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

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


# ── 多字段强 schema 抽取 (since N2) ──────────────────────────────────────────

# JSON 对象的"宽松"匹配 - 用于在自由文本里捞出第一个 { ... } 块
# 注意：不支持嵌套大括号超过 1 层，因为 LLM 实际输出嵌套不深，这里求稳不求全
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def _strip_json_envelope(raw: str) -> str:
    """剥掉常见的"外包装"，露出 JSON 主体。

    依次尝试：
      - 去 markdown code fence
      - 去解释性前缀
      - 若仍非 JSON 起头，从文本里用正则捞出第一个 { ... } 块
    返回的字符串可能仍不是合法 JSON——交给 json.loads 兜底。
    """
    text = raw.strip()
    text = _FENCE_RE.sub("", text).strip()
    # 反复剥前缀直到稳定
    for _ in range(3):
        new = _PREFIX_RE.sub("", text).strip()
        if new == text:
            break
        text = new
    # 仍不像 JSON 起头：尝试捞第一个 { ... } 块
    if not text.startswith("{"):
        match = _JSON_OBJECT_RE.search(text)
        if match:
            text = match.group(0)
    return text


def extract_structured(
    raw: str | None,
    model: type[T],
    *,
    fallback: T | None = None,
    scene: str = "",
) -> T | None:
    """从 LLM 任意输出里安全解析出一个强 schema 对象。

    防御层次：
      1. 空 / None / 全空白 → fallback
      2. 剥 markdown code fence、解释性前缀
      3. 从自由文本里捞 JSON 块（防"前后还有解释"）
      4. json.loads 解析，失败 → fallback
      5. Pydantic 严格校验：缺字段 / 类型错 / 多字段都视为污染 → fallback
      6. 所有失败路径都会写一行 logger.warning(含 scene)，便于事后排查

    Args:
        raw: LLM 原始返回（可能为 None / 整段污染 / 半截 JSON / 解释性前缀 + JSON）
        model: Pydantic BaseModel 子类，定义期望的 schema
        fallback: 校验失败时返回的兜底值（None 表示返回 None）
        scene: 仅用于日志，便于排查哪类业务调用出问题

    Returns:
        合法的 model 实例，或 fallback。绝不返回"半截"或"污染"的对象。

    Example:
        >>> from pydantic import BaseModel
        >>> class TrainingMeta(BaseModel):
        ...     topic: str
        ...     category: str
        ...     hours: int
        >>> result = extract_structured(llm_raw, TrainingMeta, scene="training_meta")
        >>> if result is None:
        ...     # 走人工 fallback 路径
        ...     ...
    """
    if raw is None or not raw.strip():
        if scene:
            logger.warning("[extract_structured/%s] empty raw input", scene)
        return fallback

    text = _strip_json_envelope(raw)

    # 解析 JSON
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError) as exc:
        if scene:
            logger.warning(
                "[extract_structured/%s] json.loads failed: %s; raw head=%r",
                scene, exc, raw[:120],
            )
        return fallback

    if not isinstance(parsed, dict):
        if scene:
            logger.warning(
                "[extract_structured/%s] parsed JSON is %s, not object",
                scene, type(parsed).__name__,
            )
        return fallback

    # Pydantic 严格校验
    try:
        return model.model_validate(parsed)
    except ValidationError as exc:
        if scene:
            logger.warning(
                "[extract_structured/%s] schema validation failed: %s",
                scene, exc.errors()[:3],
            )
        return fallback
