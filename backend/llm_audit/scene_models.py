"""Per-scene LLM model routing — pick the right model for each task.

Why: most utils today pass `model=MODEL_CHAT` for everything (extract,
match, summarise, draft). That works but wastes money: glm-5-outside is
~3x cheaper than qwen2.5-72b for tasks where accuracy doesn't matter
(short summaries, simple classifications), and DeepSeek-V3 is better than
qwen for reasoning-heavy reviews (compliance, audit cross-check).

This module owns the model→scene mapping. `traced_complete` checks here
before falling back to the caller's `model=` argument.

The mapping is read once at import time from MODEL_CHAT (the global
default) plus an optional SCENE_MODELS env var override. Hot-reload is
explicit via `reload_routing()` to keep the path predictable.

Env override example (in .env):
    SCENE_MODELS=extract_judgment_fields:DeepSeek-V3,compliance_review:DeepSeek-V3
"""
from __future__ import annotations

import logging
import os
from typing import Final

logger = logging.getLogger(__name__)


# Defaults chosen for V3:
# - extract_*  : high-accuracy structured extraction → qwen 72B
# - compliance_* / audit_*  : reasoning-heavy review → DeepSeek-V3
# - match_existing_case     : lightweight similarity check → DeepSeek-V3 (cheap)
# - intent_classify         : intent label only → DeepSeek-V3 (cheap, fast)
# - general_chat_stream     : conversational → DeepSeek-V3
# - auth_draft_*            : Chinese formal writing → qwen 72B
# - training_*              : short extraction → qwen 72B
# - vision_*                : routed externally (vision model selection)
_DEFAULT_ROUTING: Final[dict[str, str]] = {
    # Ledger extraction (structured)
    "extract_litigation_fields": "qwen2.5-72b",
    "extract_business_fields":   "qwen2.5-72b",
    "extract_judgment_fields":   "qwen2.5-72b",
    "extract_execution_fields":  "qwen2.5-72b",
    "detect_doc_type":           "DeepSeek-V3",
    "merge_case_situation":      "qwen2.5-72b",
    "match_existing_case":       "DeepSeek-V3",

    # Compliance
    "compliance_extract":        "qwen2.5-72b",
    "compliance_review":         "DeepSeek-V3",

    # Audit cross-check
    "audit_classify":            "qwen2.5-72b",
    "audit_cross_review":        "DeepSeek-V3",

    # Auth request drafting
    "auth_extract_approval_info": "qwen2.5-72b",
    "auth_draft_request":        "qwen2.5-72b",
    "auth_draft_letter_scope":   "qwen2.5-72b",

    # Training
    "training_extract_time":     "DeepSeek-V3",
    "classify_training_category": "DeepSeek-V3",

    # Chat / classifier
    "intent_classify":           "DeepSeek-V3",
    "general_chat_stream":       "DeepSeek-V3",
    # Vision scenes are NOT remapped here — vision client selection lives
    # in model_routes.resolve_vision_model and respects the user's choice.
}


def _parse_env_override(raw: str | None) -> dict[str, str]:
    """Parse 'scene1:model1,scene2:model2' into a dict. Silently ignores
    malformed entries so a typo can't take the app down."""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        scene, model = chunk.split(":", 1)
        scene, model = scene.strip(), model.strip()
        if scene and model:
            out[scene] = model
    return out


_routing: dict[str, str] = {}


def reload_routing() -> None:
    """Re-read env overrides. Call this from tests or admin endpoint."""
    global _routing
    overrides = _parse_env_override(os.getenv("SCENE_MODELS"))
    merged = {**_DEFAULT_ROUTING, **overrides}
    _routing = merged
    if overrides:
        logger.info("scene_models env overrides applied: %s", list(overrides.keys()))


def resolve_model(scene: str, fallback: str | None) -> str | None:
    """Return the model that should serve `scene`. Falls back to the
    caller-supplied model when no routing entry exists (vision scenes,
    new scenes the routing table hasn't learned about yet)."""
    if not _routing:
        reload_routing()
    return _routing.get(scene) or fallback


def current_routing() -> dict[str, str]:
    """Snapshot of effective routing — exposed for diagnostics."""
    if not _routing:
        reload_routing()
    return dict(_routing)
