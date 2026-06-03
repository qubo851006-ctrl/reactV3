"""Resilient LLM client layer.

Provides two interfaces:

  (legacy, kept for backward compat)
    get_llm_client()        -> OpenAI         (sync, used by tests + legacy code)
    get_async_llm_client()  -> AsyncOpenAI    (async, currently injected via SkillContext)

  (new since N3, recommended for new business code)
    call_llm_chat(messages, ...)              -> ChatCompletion

The new interface wraps a per-process retry / backoff / circuit-breaker /
model-fallback-chain pipeline. Business modules should migrate to it gradually
so future LLM provider flakes do not cascade into business flow failures.

Fallback chain (configured via env):
  Primary candidates:  AI_CHAT_MODELS   (comma-separated, e.g. qwen,DeepSeek,GLM)
  Last resort:         OLLAMA_BASE_URL + OLLAMA_DEFAULT_MODEL  (optional)

When the entire chain fails or the breaker trips, a DingTalk alert is fired
(with 60s dedupe), and a clear RuntimeError is raised so the caller can
surface a friendly message.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import httpx
from openai import OpenAI, AsyncOpenAI
from openai import APIError, APITimeoutError, RateLimitError, APIConnectionError
from pydantic import BaseModel

from config import (
    AIRCHINA_API_KEY,
    AIRCHINA_BASE_URL,
    AI_HTTP_HOST_HEADER,
    AI_HTTP_VERIFY_SSL,
    AI_CHAT_MODELS,
    MODEL_CHAT,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
)

logger = logging.getLogger(__name__)


# ── Public legacy helpers (DO NOT REMOVE — still used in production) ─────────

def build_ai_http_headers(host_header: str = AI_HTTP_HOST_HEADER) -> dict[str, str]:
    return {"Host": host_header} if host_header else {}


def format_llm_error(error: Exception) -> str:
    text = str(error)
    if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text:
        return (
            "❌ AI 服务连接失败:证书校验失败。当前 AI 服务地址的 TLS 证书与访问地址不匹配。"
            "如果这是内网可信服务,请优先改用证书匹配的域名或更新服务端证书;"
            "临时处理可以在后端 .env 设置 AI_HTTP_VERIFY_SSL=false 后重启服务。"
        )
    return f"❌ AI 服务连接失败:{text}"


def get_llm_client() -> OpenAI:
    return OpenAI(
        api_key=AIRCHINA_API_KEY,
        base_url=AIRCHINA_BASE_URL,
        http_client=httpx.Client(
            verify=AI_HTTP_VERIFY_SSL,
            headers=build_ai_http_headers(),
        ),
    )


def get_async_llm_client() -> AsyncOpenAI:
    """Legacy async client. New code should prefer call_llm_chat()."""
    return AsyncOpenAI(
        api_key=AIRCHINA_API_KEY,
        base_url=AIRCHINA_BASE_URL,
        http_client=httpx.AsyncClient(
            verify=AI_HTTP_VERIFY_SSL,
            headers=build_ai_http_headers(),
        ),
    )


# ── Circuit breaker (process-local) ─────────────────────────────────────────

@dataclass
class _BreakerState:
    failures: int = 0
    open_until: float = 0.0  # epoch seconds; <= now means closed


_BREAKER_THRESHOLD = int(os.getenv("LLM_BREAKER_THRESHOLD", "5"))
_BREAKER_COOLDOWN = float(os.getenv("LLM_BREAKER_COOLDOWN_SEC", "30"))
_breaker = _BreakerState()


def _breaker_is_open(now: float | None = None) -> bool:
    return (now or time.time()) < _breaker.open_until


def _breaker_record_success() -> None:
    _breaker.failures = 0
    _breaker.open_until = 0.0


def _breaker_record_failure(now: float | None = None) -> bool:
    """Increment failure counter. Returns True if breaker just opened."""
    _breaker.failures += 1
    if _breaker.failures >= _BREAKER_THRESHOLD and not _breaker_is_open(now):
        _breaker.open_until = (now or time.time()) + _BREAKER_COOLDOWN
        logger.warning(
            "[LLM] circuit breaker OPEN for %.0fs after %d consecutive failures",
            _BREAKER_COOLDOWN, _breaker.failures,
        )
        return True
    return False


def _reset_breaker_for_tests() -> None:
    """Test helper. Do NOT call from business code."""
    _breaker.failures = 0
    _breaker.open_until = 0.0


# ── Alert dedupe (process-local) ────────────────────────────────────────────

_ALERT_DEDUPE_WINDOW_SEC = float(os.getenv("LLM_ALERT_DEDUPE_SEC", "60"))
_last_alert_at: dict[str, float] = {}


def _should_fire_alert(key: str, now: float | None = None) -> bool:
    t = now or time.time()
    last = _last_alert_at.get(key, 0.0)
    if (t - last) < _ALERT_DEDUPE_WINDOW_SEC:
        return False
    _last_alert_at[key] = t
    return True


def _reset_alerts_for_tests() -> None:
    """Test helper."""
    _last_alert_at.clear()


# ── DingTalk alert hook (overridable for tests) ─────────────────────────────

# Type: (title: str, summary: str, level: str) -> None
AlertSink = Callable[[str, str, str], None]


def _default_alert_sink(title: str, summary: str, level: str) -> None:
    """Best-effort DingTalk alert. Imported lazily to avoid hard coupling."""
    try:
        from integrations.dingtalk.notifications import send_dingtalk_notification
        send_dingtalk_notification(
            title=title,
            summary=summary,
            level=level,
            task="llm_client",
            stage="resilience",
        )
    except Exception as e:
        logger.warning("[LLM] alert sink failed: %s", e)


_alert_sink: AlertSink = _default_alert_sink


def set_alert_sink(sink: AlertSink) -> None:
    """Override for tests."""
    global _alert_sink
    _alert_sink = sink


def reset_alert_sink() -> None:
    global _alert_sink
    _alert_sink = _default_alert_sink


# ── Model fallback chain ────────────────────────────────────────────────────

def _build_fallback_chain(preferred: str | None) -> list[str]:
    """Order: preferred → other AI_CHAT_MODELS → (none here, Ollama handled separately)."""
    primary = preferred or MODEL_CHAT
    candidates = [primary]
    for m in (AI_CHAT_MODELS or []):
        if m and m != primary and m not in candidates:
            candidates.append(m)
    return candidates


def _is_retryable_error(exc: Exception) -> bool:
    """True iff caller should retry the SAME model with backoff."""
    if isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError)):
        return True
    if isinstance(exc, APIError):
        status = getattr(exc, "status_code", None)
        return status is not None and 500 <= status < 600
    return False


# ── Main entry point ────────────────────────────────────────────────────────

# Factory for AsyncOpenAI — overridable in tests.
# Signature: (api_key, base_url, verify, headers) -> AsyncOpenAI
_ClientFactory = Callable[..., AsyncOpenAI]


def _default_async_client_factory(*, api_key: str, base_url: str, verify: bool, headers: dict[str, str]) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=httpx.AsyncClient(verify=verify, headers=headers, timeout=30.0),
    )


_client_factory: _ClientFactory = _default_async_client_factory


def set_client_factory(factory: _ClientFactory) -> None:
    """Override for tests."""
    global _client_factory
    _client_factory = factory


def reset_client_factory() -> None:
    global _client_factory
    _client_factory = _default_async_client_factory


async def call_llm_chat(
    messages: list[dict[str, Any]],
    *,
    preferred_model: str | None = None,
    scene: str = "chat",
    max_retries: int = 3,
    timeout: float = 30.0,
    **kwargs: Any,
) -> Any:
    """Resilient chat-completion call.

    Order of attempts:
      1. preferred_model (default = MODEL_CHAT) on primary endpoint, retried `max_retries` times
      2. each remaining model in AI_CHAT_MODELS on primary endpoint, with retry
      3. local Ollama if OLLAMA_BASE_URL is configured

    Raises RuntimeError if breaker is open or every path fails.

    `scene` is used purely for telemetry / alert messages.
    """
    if _breaker_is_open():
        msg = (
            f"AI 服务暂时不可用(circuit breaker open for {scene}),"
            f"请约 {int(_breaker.open_until - time.time())} 秒后重试。"
        )
        raise RuntimeError(msg)

    chain = _build_fallback_chain(preferred_model)
    last_error: Exception | None = None
    degraded = False  # flipped True once first model fails

    for model_idx, model in enumerate(chain):
        client = _client_factory(
            api_key=AIRCHINA_API_KEY,
            base_url=AIRCHINA_BASE_URL,
            verify=AI_HTTP_VERIFY_SSL,
            headers=build_ai_http_headers(),
        )

        for attempt in range(max_retries):
            try:
                resp = await client.chat.completions.create(
                    model=model, messages=messages, timeout=timeout, **kwargs
                )
                _breaker_record_success()
                if degraded:
                    logger.warning(
                        "[LLM] degraded success: scene=%s served by fallback model=%s",
                        scene, model,
                    )
                    if _should_fire_alert(f"degraded:{scene}"):
                        _alert_sink(
                            "AI 服务降级",
                            f"场景 {scene} 的主模型不可用,已自动降级到 {model} 完成本次请求。",
                            "warning",
                        )
                return resp

            except Exception as exc:
                last_error = exc
                if _is_retryable_error(exc) and attempt < max_retries - 1:
                    wait = min(2 ** attempt, 8)
                    logger.warning(
                        "[LLM] retryable error on model=%s attempt=%d/%d: %s — sleeping %ds",
                        model, attempt + 1, max_retries, type(exc).__name__, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                # Non-retryable or out of retries -> switch model
                degraded = True
                logger.warning(
                    "[LLM] model %s exhausted (%s), falling back to next",
                    model, type(exc).__name__,
                )
                break

    # All cloud models exhausted -> try local Ollama if configured
    if OLLAMA_BASE_URL:
        try:
            logger.warning("[LLM] all cloud models down; trying local Ollama fallback")
            ollama_client = _client_factory(
                api_key=OLLAMA_API_KEY,
                base_url=OLLAMA_BASE_URL,
                verify=False,
                headers={},
            )
            resp = await ollama_client.chat.completions.create(
                model=chain[0],  # ollama may have a matching model name
                messages=messages,
                timeout=timeout * 2,
                **kwargs,
            )
            _breaker_record_success()
            if _should_fire_alert(f"ollama:{scene}"):
                _alert_sink(
                    "AI 服务降级至本地 Ollama",
                    f"场景 {scene} 的全部云端模型均不可用,已自动降级到本地 Ollama 完成本次请求,请关注网络与配额。",
                    "warning",
                )
            return resp
        except Exception as exc:
            last_error = exc
            logger.error("[LLM] Ollama fallback also failed: %s", exc)

    # Total failure
    breaker_just_opened = _breaker_record_failure()
    err_type = type(last_error).__name__ if last_error else "Unknown"
    err_text = str(last_error) if last_error else "(no error captured)"

    if breaker_just_opened:
        if _should_fire_alert("breaker_open"):
            _alert_sink(
                "AI 服务断路器打开",
                f"已连续 {_BREAKER_THRESHOLD} 次调用失败,断路器已打开 {int(_BREAKER_COOLDOWN)} 秒。最后错误:{err_type}: {err_text[:200]}",
                "error",
            )
    else:
        if _should_fire_alert(f"total_failure:{scene}"):
            _alert_sink(
                "AI 服务全链路失败",
                f"场景 {scene} 在主模型 + 备选模型 + 本地 Ollama 全部失败。错误:{err_type}: {err_text[:200]}",
                "error",
            )

    raise RuntimeError(
        f"AI 服务暂时全部不可用(已尝试 {len(chain)} 个云端模型 + Ollama 兜底)。"
        f"最后错误:{err_type}: {err_text[:200]}"
    )


# ── Synchronous resilient call (sunk into llm_audit.traced_complete) ─────────

# Sync OpenAI factory for the Ollama fallback leg — overridable in tests so the
# sync resilience path can be exercised without real network / Ollama traffic.
def _default_sync_ollama_factory() -> OpenAI:
    return OpenAI(
        api_key=OLLAMA_API_KEY,
        base_url=OLLAMA_BASE_URL,
        http_client=httpx.Client(verify=False, headers={}, timeout=60.0),
    )


_sync_ollama_factory: Callable[[], OpenAI] = _default_sync_ollama_factory


def set_sync_ollama_factory(factory: Callable[[], OpenAI]) -> None:
    """Override for tests."""
    global _sync_ollama_factory
    _sync_ollama_factory = factory


def reset_sync_ollama_factory() -> None:
    global _sync_ollama_factory
    _sync_ollama_factory = _default_sync_ollama_factory


def complete_with_resilience(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, Any]],
    scene: str = "chat",
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
    """Synchronous resilient chat-completion using a caller-supplied client.

    Mirrors :func:`call_llm_chat`'s retry / backoff / circuit-breaker /
    model-fallback-chain / DingTalk-alert behaviour, with two differences that
    let it slot underneath ``llm_audit.traced_complete`` transparently:

      * it is **synchronous** (traced_complete runs inside a sync span), and
      * it reuses the **caller-supplied ``client``** for every cloud model in
        the chain (only the ``model`` name varies) — all AI_CHAT_MODELS are
        served by the same AIRCHINA endpoint, so one client is correct.

    All decision logic (breaker / chain / retryability / alert dedupe) is the
    same process-local state shared with :func:`call_llm_chat` — there is no
    second copy of the policy.

    Order of attempts:
      1. ``model`` (per-scene-resolved by the caller) retried ``max_retries`` times
      2. each remaining model in ``AI_CHAT_MODELS`` with retry
      3. local Ollama if ``OLLAMA_BASE_URL`` is configured

    Raises ``RuntimeError`` if the breaker is open or every path fails — same
    contract as the legacy raw call, so traced_complete keeps propagating LLM
    failures to its caller. Intermediate retries / fallbacks are transparent.

    ``scene`` is used purely for telemetry / alert messages.
    """
    if _breaker_is_open():
        raise RuntimeError(
            f"AI 服务暂时不可用(circuit breaker open for {scene}),"
            f"请约 {int(_breaker.open_until - time.time())} 秒后重试。"
        )

    chain = _build_fallback_chain(model)
    last_error: Exception | None = None
    degraded = False  # flipped True once the first model fails

    for model_name in chain:
        for attempt in range(max_retries):
            try:
                resp = client.chat.completions.create(
                    model=model_name, messages=messages, **kwargs
                )
                _breaker_record_success()
                if degraded:
                    logger.warning(
                        "[LLM] degraded success (sync): scene=%s served by fallback model=%s",
                        scene, model_name,
                    )
                    if _should_fire_alert(f"degraded:{scene}"):
                        _alert_sink(
                            "AI 服务降级",
                            f"场景 {scene} 的主模型不可用,已自动降级到 {model_name} 完成本次请求。",
                            "warning",
                        )
                return resp

            except Exception as exc:
                last_error = exc
                if _is_retryable_error(exc) and attempt < max_retries - 1:
                    wait = min(2 ** attempt, 8)
                    logger.warning(
                        "[LLM] retryable error (sync) on model=%s attempt=%d/%d: %s — sleeping %ds",
                        model_name, attempt + 1, max_retries, type(exc).__name__, wait,
                    )
                    time.sleep(wait)
                    continue
                degraded = True
                logger.warning(
                    "[LLM] model %s exhausted (sync, %s), falling back to next",
                    model_name, type(exc).__name__,
                )
                break

    # All cloud models exhausted -> try local Ollama if configured
    if OLLAMA_BASE_URL:
        try:
            logger.warning("[LLM] all cloud models down (sync); trying local Ollama fallback")
            ollama_client = _sync_ollama_factory()
            resp = ollama_client.chat.completions.create(
                model=chain[0], messages=messages, **kwargs
            )
            _breaker_record_success()
            if _should_fire_alert(f"ollama:{scene}"):
                _alert_sink(
                    "AI 服务降级至本地 Ollama",
                    f"场景 {scene} 的全部云端模型均不可用,已自动降级到本地 Ollama 完成本次请求,请关注网络与配额。",
                    "warning",
                )
            return resp
        except Exception as exc:
            last_error = exc
            logger.error("[LLM] Ollama fallback (sync) also failed: %s", exc)

    # Total failure
    breaker_just_opened = _breaker_record_failure()
    err_type = type(last_error).__name__ if last_error else "Unknown"
    err_text = str(last_error) if last_error else "(no error captured)"

    if breaker_just_opened:
        if _should_fire_alert("breaker_open"):
            _alert_sink(
                "AI 服务断路器打开",
                f"已连续 {_BREAKER_THRESHOLD} 次调用失败,断路器已打开 {int(_BREAKER_COOLDOWN)} 秒。最后错误:{err_type}: {err_text[:200]}",
                "error",
            )
    else:
        if _should_fire_alert(f"total_failure:{scene}"):
            _alert_sink(
                "AI 服务全链路失败",
                f"场景 {scene} 在主模型 + 备选模型 + 本地 Ollama 全部失败。错误:{err_type}: {err_text[:200]}",
                "error",
            )

    raise RuntimeError(
        f"AI 服务暂时全部不可用(已尝试 {len(chain)} 个云端模型 + Ollama 兜底)。"
        f"最后错误:{err_type}: {err_text[:200]}"
    )


# ── Structured output helper (since N2) ─────────────────────────────────────

T_Model = TypeVar("T_Model", bound=BaseModel)


async def call_llm_structured(
    messages: list[dict[str, Any]],
    model: type[T_Model],
    *,
    preferred_model: str | None = None,
    scene: str = "structured",
    fallback: T_Model | None = None,
    max_retries: int = 3,
    timeout: float = 30.0,
    try_json_mode: bool = True,
    **kwargs: Any,
) -> T_Model | None:
    """Resilient chat-completion + strict Pydantic schema parsing.

    Combines:
      - call_llm_chat's retry / breaker / fallback chain
      - utils.llm_extract.extract_structured's defensive JSON parsing
      - OpenAI's response_format={"type":"json_object"} when supported

    Failure modes — all return `fallback`, never a half-valid model:
      - LLM returned non-JSON / markdown-wrapped JSON
      - LLM returned valid JSON but schema mismatch
      - LLM returned narrative with JSON embedded (gets auto-extracted)
      - LLM call itself raised (after exhausting fallback chain)

    Args:
        messages: chat messages
        model: Pydantic BaseModel subclass defining expected schema
        scene: telemetry tag (e.g. "training_meta", "compliance_extract")
        fallback: returned on ANY parsing/validation failure (default None)
        try_json_mode: if True, attempt response_format={"type":"json_object"};
                       silently retry without it if the model rejects the format
                       (some non-OpenAI providers don't support it)

    Returns:
        Validated `model` instance, or `fallback`.
    """
    # Lazy import to avoid circular dependency between llm_client and utils
    from utils.llm_extract import extract_structured

    call_kwargs = dict(kwargs)
    if try_json_mode and "response_format" not in call_kwargs:
        call_kwargs["response_format"] = {"type": "json_object"}

    try:
        resp = await call_llm_chat(
            messages,
            preferred_model=preferred_model,
            scene=scene,
            max_retries=max_retries,
            timeout=timeout,
            **call_kwargs,
        )
    except Exception as exc:
        # If response_format triggered the failure on the FIRST attempt only,
        # retry once without it. We detect this by inspecting the error text.
        text = str(exc).lower()
        if (
            try_json_mode
            and ("response_format" in text or "json_object" in text or "json mode" in text)
        ):
            logger.warning(
                "[call_llm_structured/%s] provider rejected JSON mode; retrying without it",
                scene,
            )
            call_kwargs.pop("response_format", None)
            try:
                resp = await call_llm_chat(
                    messages,
                    preferred_model=preferred_model,
                    scene=scene,
                    max_retries=max_retries,
                    timeout=timeout,
                    **call_kwargs,
                )
            except Exception:
                logger.warning(
                    "[call_llm_structured/%s] retry without json_mode also failed",
                    scene,
                )
                return fallback
        else:
            logger.warning(
                "[call_llm_structured/%s] LLM call failed: %s: %s",
                scene, type(exc).__name__, str(exc)[:200],
            )
            return fallback

    # Extract raw content from OpenAI ChatCompletion response
    try:
        raw = resp.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        logger.warning(
            "[call_llm_structured/%s] cannot read response.choices[0].message.content: %s",
            scene, exc,
        )
        return fallback

    return extract_structured(raw, model, fallback=fallback, scene=scene)
