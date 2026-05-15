import json
from pathlib import Path
from typing import Any

from config import (
    AI_CHAT_MODELS,
    AI_VISION_MODELS,
    DATA_ROOT,
    MODEL_CHAT,
    MODEL_INTENT,
    MODEL_VISION,
    resolve_model,
)
from file_store import atomic_write_text, file_lock

MODEL_ROUTES_PATH = Path(DATA_ROOT) / "model_routes.json"

# ── 内存缓存（避免在 async 端点中重复同步读文件阻塞事件循环）──────
_routes_cache: dict[str, Any] | None = None


def _get_cached_routes() -> dict[str, Any]:
    """返回内存中缓存的路由配置，首次调用时从磁盘加载。"""
    global _routes_cache
    if _routes_cache is None:
        _routes_cache = load_model_routes()
    return _routes_cache


def _invalidate_routes_cache() -> None:
    """写入新配置后调用，使下次 _get_cached_routes() 重新读盘。"""
    global _routes_cache
    _routes_cache = None


def _label_for_model(value: str) -> str:
    labels = {
        "qwen2.5-72b": "Qwen2.5 72B",
        "qwen2.5-vl-72b": "Qwen2.5 VL 72B",
        "qwen3-vl:8b": "Qwen3 VL 8B (本地)",
        "DeepSeek-V3": "DeepSeek V3",
        "DeepSeek-R1": "DeepSeek R1",
        "glm-5-outside": "GLM-5",
        "deepseek-v3.2-outside": "DeepSeek V3.2",
    }
    return labels.get(value, value)


def _model_options(values: list[str]) -> list[dict[str, str]]:
    return [{"value": value, "label": _label_for_model(value)} for value in values]


def _normalize_models(raw: Any, fallback: list[str]) -> list[str]:
    values: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            value = ""
            if isinstance(item, str):
                value = item.strip()
            elif isinstance(item, dict):
                value = str(item.get("value") or "").strip()
            if value and value not in values:
                values.append(value)
    return values or list(fallback)


def _default_routes() -> dict[str, Any]:
    chat_models = list(AI_CHAT_MODELS)
    vision_models = list(AI_VISION_MODELS)
    return {
        "default_chat_model": resolve_model("qwen2.5-72b", chat_models, MODEL_CHAT),
        "default_intent_model": resolve_model("qwen2.5-72b", chat_models, MODEL_INTENT),
        "default_vision_model": resolve_model("qwen2.5-vl-72b", vision_models, MODEL_VISION),
        "chat_models": chat_models,
        "vision_models": vision_models,
    }


def load_model_routes(path: Path = MODEL_ROUTES_PATH) -> dict[str, Any]:
    defaults = _default_routes()
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

    chat_models = _normalize_models(raw.get("chat_models"), defaults["chat_models"])
    vision_models = _normalize_models(raw.get("vision_models"), defaults["vision_models"])
    return {
        "default_chat_model": resolve_model(raw.get("default_chat_model"), chat_models, defaults["default_chat_model"]),
        "default_intent_model": resolve_model(raw.get("default_intent_model"), chat_models, defaults["default_intent_model"]),
        "default_vision_model": resolve_model(raw.get("default_vision_model"), vision_models, defaults["default_vision_model"]),
        "chat_models": chat_models,
        "vision_models": vision_models,
    }


def public_model_routes(path: Path = MODEL_ROUTES_PATH) -> dict[str, Any]:
    routes = load_model_routes(path)
    return {
        "default_chat_model": routes["default_chat_model"],
        "default_vision_model": routes["default_vision_model"],
        "chat_models": _model_options(routes["chat_models"]),
        "vision_models": _model_options(routes["vision_models"]),
    }


def save_model_routes(payload: dict[str, Any], path: Path = MODEL_ROUTES_PATH) -> dict[str, Any]:
    routes = load_model_routes(path)
    chat_models = _normalize_models(payload.get("chat_models"), routes["chat_models"])
    vision_models = _normalize_models(payload.get("vision_models"), routes["vision_models"])
    saved = {
        "default_chat_model": resolve_model(payload.get("default_chat_model"), chat_models, routes["default_chat_model"]),
        "default_intent_model": resolve_model(payload.get("default_intent_model"), chat_models, routes["default_intent_model"]),
        "default_vision_model": resolve_model(payload.get("default_vision_model"), vision_models, routes["default_vision_model"]),
        "chat_models": chat_models,
        "vision_models": vision_models,
    }
    with file_lock(path):
        atomic_write_text(path, json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    _invalidate_routes_cache()
    return saved


def ensure_model_routes_file(path: Path = MODEL_ROUTES_PATH) -> None:
    if not path.exists():
        save_model_routes(_default_routes(), path)


def resolve_chat_model(requested: str | None) -> str:
    routes = _get_cached_routes()
    return resolve_model(requested, routes["chat_models"], routes["default_chat_model"])


def resolve_intent_model() -> str:
    routes = _get_cached_routes()
    return resolve_model(routes["default_intent_model"], routes["chat_models"], routes["default_chat_model"])


def resolve_vision_model(requested: str | None) -> str:
    routes = _get_cached_routes()
    return resolve_model(requested, routes["vision_models"], routes["default_vision_model"])
