"""Self-improving prompts via few-shot examples drawn from user corrections.

Idea: every time a user reviews an LLM extraction and corrects it, we record
(input, edited_to) in the llm_traces row. The next call to the same scene
queries those corrections, picks the best K, and prepends them as a "here's
what the human actually wanted" hint to the system prompt.

Selection policy (deliberately simple — this is v1):
- only rows with accepted=True AND edited_to IS NOT NULL (i.e. the user
  kept the result but changed something)
- only the same scene
- order by created_at DESC (most recent first)
- de-dupe by input_hash so the same correction isn't shown twice
- cap at MAX_EXAMPLES_PER_SCENE

What we deliberately don't do (yet):
- relevance scoring (similarity between current input and example inputs)
  — would need embeddings; v1 trusts recency
- mixing scenes
- fine-tuning

Vision scenes (input contains base64 images) are NEVER eligible — examples
would blow up the prompt and aren't transferrable. Caller filters them out
before calling `compose_system_prefix`.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from sqlalchemy import desc, select

from llm_audit.db import get_audit_session_factory
from llm_audit.models import LLMTrace


logger = logging.getLogger(__name__)

MAX_EXAMPLES_PER_SCENE = 5
MAX_EXAMPLE_INPUT_CHARS = 1500   # truncate each example input so prompts stay sane
MAX_EXAMPLE_OUTPUT_CHARS = 1500
CACHE_TTL_SECONDS = 60            # per-scene cache to avoid hammering PG on every call

# Scenes whose inputs include image base64 — never inject few-shot.
VISION_SCENE_PREFIXES = ("vision_", "ledger.vision_")


# Per-process TTL cache so concurrent extracts don't fan out into N parallel
# PG queries (and don't serialise on Python's import lock either).
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _cache_get(scene: str) -> list[dict[str, Any]] | None:
    with _cache_lock:
        entry = _cache.get(scene)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() >= expires_at:
        return None
    return value


def _cache_set(scene: str, examples: list[dict[str, Any]]) -> None:
    with _cache_lock:
        _cache[scene] = (time.monotonic() + CACHE_TTL_SECONDS, examples)


def invalidate_cache(scene: str | None = None) -> None:
    """Drop cached examples for one scene (or all). Call this from the
    feedback endpoint so fresh corrections show up promptly."""
    with _cache_lock:
        if scene is None:
            _cache.clear()
        else:
            _cache.pop(scene, None)


def is_vision_scene(scene: str) -> bool:
    return any(scene.startswith(p) for p in VISION_SCENE_PREFIXES)


def fetch_examples(scene: str, limit: int = MAX_EXAMPLES_PER_SCENE) -> list[dict[str, Any]]:
    """Return up to `limit` accepted+edited examples for the scene, newest first.

    Each example is `{input_text, edited_to}`. Cached for CACHE_TTL_SECONDS
    so concurrent extracts don't fan out into N parallel PG queries.
    Returns [] on any failure (DB down, audit disabled) so calls never break.
    """
    if is_vision_scene(scene):
        return []
    cached = _cache_get(scene)
    if cached is not None:
        return cached

    SessionLocal = get_audit_session_factory()
    if SessionLocal is None:
        _cache_set(scene, [])
        return []
    try:
        with SessionLocal() as s:
            rows = s.execute(
                select(LLMTrace)
                .where(LLMTrace.scene == scene)
                .where(LLMTrace.accepted.is_(True))
                .where(LLMTrace.edited_to.is_not(None))
                .order_by(desc(LLMTrace.created_at))
                .limit(limit * 3)  # over-fetch to allow input_hash dedup
            ).scalars().all()
    except Exception:
        logger.exception("few_shot fetch failed for scene=%s", scene)
        _cache_set(scene, [])  # cache the failure briefly to avoid retry storms
        return []

    seen_hashes: set[str] = set()
    examples: list[dict[str, Any]] = []
    for row in rows:
        if row.input_hash in seen_hashes:
            continue
        seen_hashes.add(row.input_hash)
        examples.append({
            "input_text": (row.input_text or "")[:MAX_EXAMPLE_INPUT_CHARS],
            "edited_to": (row.edited_to or "")[:MAX_EXAMPLE_OUTPUT_CHARS],
        })
        if len(examples) >= limit:
            break
    _cache_set(scene, examples)
    return examples


def compose_system_prefix(examples: list[dict[str, Any]]) -> str | None:
    """Render examples as a short system prompt fragment, or None if empty."""
    if not examples:
        return None
    parts = [
        "以下是历史上同类任务中用户最终采纳的结果，请优先参照这些示例的字段格式、术语和结构：",
        "",
    ]
    for i, ex in enumerate(examples, 1):
        parts.append(f"【示例 {i}】")
        parts.append("【输入摘要】")
        # input_text 是 JSON-serialised messages; render compactly
        preview = ex["input_text"]
        try:
            decoded = json.loads(preview)
            if isinstance(decoded, list):
                # last user-role content
                for msg in decoded:
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        content = msg.get("content")
                        if isinstance(content, str):
                            preview = content
                            break
        except (json.JSONDecodeError, ValueError):
            pass
        parts.append(preview[:MAX_EXAMPLE_INPUT_CHARS])
        parts.append("【用户采纳的输出】")
        parts.append(ex["edited_to"][:MAX_EXAMPLE_OUTPUT_CHARS])
        parts.append("")
    parts.append("现在请处理当前任务：")
    return "\n".join(parts)


def maybe_inject(messages: list[dict], scene: str) -> list[dict]:
    """Return a new message list with a few-shot system prefix prepended if
    examples exist. Safe to call from every traced_complete invocation —
    when no examples or DB unavailable, returns `messages` unchanged."""
    if is_vision_scene(scene):
        return messages
    examples = fetch_examples(scene)
    prefix = compose_system_prefix(examples)
    if prefix is None:
        return messages
    return [{"role": "system", "content": prefix}, *messages]
