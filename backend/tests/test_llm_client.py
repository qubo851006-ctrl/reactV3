"""Tests for the resilient LLM client layer (N3).

Coverage (8 cases):
  1. Happy path: primary model succeeds first try
  2. Retry: primary fails with RateLimit, succeeds on retry
  3. Model fallback: primary exhausted, second cloud model serves
  4. Ollama fallback: all cloud models down, Ollama serves
  5. Total failure: every path fails, breaker opens, alert fired
  6. Breaker open rejects immediately without hitting the client
  7. Breaker auto-resets after cooldown
  8. Alert dedupe: same key within 60s only fires once

All cases mock the OpenAI client factory and the alert sink — no real
network calls, no DingTalk traffic. Uses unittest.IsolatedAsyncioTestCase
to match the rest of the V3 backend test suite (no pytest-asyncio).
"""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from openai import APIError, RateLimitError

import llm_client


def _make_api_error(status: int) -> APIError:
    err = APIError(message=f"http {status}", request=MagicMock(), body=None)
    err.status_code = status
    return err


def _make_rate_limit() -> RateLimitError:
    return RateLimitError(
        message="rate limited",
        response=SimpleNamespace(status_code=429, request=MagicMock(), headers={}),
        body=None,
    )


def _make_fake_client(behaviour_per_model: dict[str, list]) -> MagicMock:
    """Fake AsyncOpenAI dispatching by model name; each entry is exc-or-value."""
    async def dispatch(*, model: str, **kwargs):
        queue = behaviour_per_model.get(model)
        if not queue:
            raise APIError(message=f"empty queue for {model}", request=MagicMock(), body=None)
        nxt = queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=dispatch)
    return client


class LLMClientResilienceTests(unittest.IsolatedAsyncioTestCase):
    """All scenarios use a fixed 3-model chain: qwen-primary, deepseek-backup, glm-third."""

    def setUp(self) -> None:
        llm_client._reset_breaker_for_tests()
        llm_client._reset_alerts_for_tests()
        llm_client.reset_alert_sink()
        llm_client.reset_client_factory()

        # Deterministic chain
        self._orig_model_chat = llm_client.MODEL_CHAT
        self._orig_chat_models = llm_client.AI_CHAT_MODELS
        self._orig_ollama = llm_client.OLLAMA_BASE_URL
        llm_client.MODEL_CHAT = "qwen-primary"
        llm_client.AI_CHAT_MODELS = ["qwen-primary", "deepseek-backup", "glm-third"]
        llm_client.OLLAMA_BASE_URL = ""  # default off; individual tests opt-in

        # No real sleeps in retry backoff
        self._orig_sleep = llm_client.asyncio.sleep
        llm_client.asyncio.sleep = AsyncMock()

        # Capture alerts
        self.alerts: list[tuple[str, str, str]] = []
        llm_client.set_alert_sink(
            lambda title, summary, level: self.alerts.append((title, summary, level))
        )

    def tearDown(self) -> None:
        llm_client.MODEL_CHAT = self._orig_model_chat
        llm_client.AI_CHAT_MODELS = self._orig_chat_models
        llm_client.OLLAMA_BASE_URL = self._orig_ollama
        llm_client.asyncio.sleep = self._orig_sleep
        llm_client.reset_alert_sink()
        llm_client.reset_client_factory()
        llm_client._reset_breaker_for_tests()
        llm_client._reset_alerts_for_tests()

    # ── Case 1 ──────────────────────────────────────────────────────────────
    async def test_1_happy_path_primary_success(self):
        resp_marker = SimpleNamespace(id="ok-1")
        client = _make_fake_client({"qwen-primary": [resp_marker]})
        llm_client.set_client_factory(lambda **kwargs: client)

        result = await llm_client.call_llm_chat([{"role": "user", "content": "hi"}])

        self.assertIs(result, resp_marker)
        self.assertEqual(client.chat.completions.create.await_count, 1)
        self.assertEqual(self.alerts, [], "happy path must not fire alerts")
        self.assertEqual(llm_client._breaker.failures, 0)

    # ── Case 2 ──────────────────────────────────────────────────────────────
    async def test_2_retry_after_rate_limit(self):
        resp_marker = SimpleNamespace(id="ok-2")
        client = _make_fake_client({
            "qwen-primary": [_make_rate_limit(), resp_marker],
        })
        llm_client.set_client_factory(lambda **kwargs: client)

        result = await llm_client.call_llm_chat([{"role": "user", "content": "hi"}])

        self.assertIs(result, resp_marker)
        self.assertEqual(client.chat.completions.create.await_count, 2)
        self.assertEqual(self.alerts, [], "in-model retry must not fire alerts")
        llm_client.asyncio.sleep.assert_awaited()

    # ── Case 3 ──────────────────────────────────────────────────────────────
    async def test_3_fallback_to_second_cloud_model(self):
        resp_marker = SimpleNamespace(id="ok-3")
        client = _make_fake_client({
            "qwen-primary": [_make_api_error(503), _make_api_error(503), _make_api_error(503)],
            "deepseek-backup": [resp_marker],
        })
        llm_client.set_client_factory(lambda **kwargs: client)

        result = await llm_client.call_llm_chat(
            [{"role": "user", "content": "hi"}], scene="audit"
        )

        self.assertIs(result, resp_marker)
        self.assertEqual(len(self.alerts), 1, "degraded path fires one warning alert")
        title, summary, level = self.alerts[0]
        self.assertEqual(level, "warning")
        self.assertIn("降级", title)
        self.assertIn("audit", summary)
        self.assertEqual(llm_client._breaker.failures, 0)

    # ── Case 4 ──────────────────────────────────────────────────────────────
    async def test_4_ollama_fallback_when_all_cloud_down(self):
        llm_client.OLLAMA_BASE_URL = "http://192.168.9.226:11434/v1"

        resp_marker = SimpleNamespace(id="ok-4")
        # Same fake client serves both cloud (failures) and Ollama (success on
        # the qwen-primary slot since impl passes chain[0] to Ollama).
        behaviours: dict[str, list] = {
            "qwen-primary":   [_make_api_error(503)] * 3 + [resp_marker],
            "deepseek-backup":[_make_api_error(503)] * 3,
            "glm-third":      [_make_api_error(503)] * 3,
        }
        async def dispatch(*, model: str, **kwargs):
            q = behaviours.get(model, [])
            if not q:
                raise APIError(message=f"empty {model}", request=MagicMock(), body=None)
            nxt = q.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=dispatch)
        llm_client.set_client_factory(lambda **kwargs: client)

        result = await llm_client.call_llm_chat(
            [{"role": "user", "content": "hi"}], scene="compliance"
        )

        self.assertIs(result, resp_marker)
        self.assertEqual(len(self.alerts), 1)
        title, _, level = self.alerts[0]
        self.assertEqual(level, "warning")
        self.assertIn("Ollama", title)

    # ── Case 5 ──────────────────────────────────────────────────────────────
    async def test_5_total_failure_opens_breaker_and_alerts(self):
        llm_client.OLLAMA_BASE_URL = ""
        client = _make_fake_client({
            "qwen-primary":   [_make_api_error(503)] * 3,
            "deepseek-backup":[_make_api_error(503)] * 3,
            "glm-third":      [_make_api_error(503)] * 3,
        })
        llm_client.set_client_factory(lambda **kwargs: client)

        with self.assertRaises(RuntimeError) as ctx:
            await llm_client.call_llm_chat(
                [{"role": "user", "content": "hi"}], scene="ledger"
            )

        self.assertIn("全部不可用", str(ctx.exception))
        self.assertEqual(llm_client._breaker.failures, 1)
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.alerts[0][2], "error")
        self.assertIn("ledger", self.alerts[0][1])

    # ── Case 6 ──────────────────────────────────────────────────────────────
    async def test_6_open_breaker_rejects_immediately(self):
        llm_client._breaker.failures = llm_client._BREAKER_THRESHOLD
        llm_client._breaker.open_until = time.time() + 30

        client = _make_fake_client({"qwen-primary": [SimpleNamespace(id="unused")]})
        llm_client.set_client_factory(lambda **kwargs: client)

        with self.assertRaises(RuntimeError) as ctx:
            await llm_client.call_llm_chat([{"role": "user", "content": "hi"}])

        self.assertIn("circuit breaker", str(ctx.exception))
        self.assertEqual(
            client.chat.completions.create.await_count, 0,
            "open breaker must not call the client",
        )

    # ── Case 7 ──────────────────────────────────────────────────────────────
    async def test_7_breaker_resets_after_cooldown(self):
        # Pretend breaker opened ~70s ago with 30s cooldown -> already expired
        llm_client._breaker.failures = llm_client._BREAKER_THRESHOLD
        llm_client._breaker.open_until = time.time() - 70

        resp_marker = SimpleNamespace(id="ok-7")
        client = _make_fake_client({"qwen-primary": [resp_marker]})
        llm_client.set_client_factory(lambda **kwargs: client)

        result = await llm_client.call_llm_chat([{"role": "user", "content": "hi"}])

        self.assertIs(result, resp_marker)
        self.assertEqual(llm_client._breaker.failures, 0, "success resets failure counter")

    # ── Case 8 ──────────────────────────────────────────────────────────────
    async def test_8_alert_dedupe_within_60s(self):
        llm_client.OLLAMA_BASE_URL = ""
        behaviours: dict[str, list] = {
            "qwen-primary":   [_make_api_error(503)] * 6,
            "deepseek-backup":[_make_api_error(503)] * 6,
            "glm-third":      [_make_api_error(503)] * 6,
        }
        async def dispatch(*, model: str, **kwargs):
            q = behaviours.get(model, [])
            if not q:
                raise APIError(message=f"empty {model}", request=MagicMock(), body=None)
            raise q.pop(0)
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=dispatch)
        llm_client.set_client_factory(lambda **kwargs: client)

        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await llm_client.call_llm_chat(
                    [{"role": "user", "content": "hi"}], scene="training"
                )

        same_scene = [a for a in self.alerts if "training" in a[1]]
        self.assertEqual(
            len(same_scene), 1,
            f"expected exactly 1 dedupe'd alert; got {len(same_scene)}: {same_scene}",
        )


if __name__ == "__main__":
    unittest.main()
