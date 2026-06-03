"""Tests for the SYNC resilient LLM call (v3.6.15).

`llm_client.complete_with_resilience` is the synchronous twin of
`call_llm_chat`, sunk underneath `llm_audit.traced_complete` so every traced
business call gains retry / backoff / circuit-breaker / model-fallback /
DingTalk-alert without losing its audit span.

Coverage mirrors test_llm_client.py (8 cases) but synchronous, plus one
integration case proving traced_complete records the *actually served* model
after a resilience fallback.

All cases mock the OpenAI sync client + alert sink + time.sleep — no real
network, no DingTalk, no wall-clock sleeps.
"""

from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    """Fake sync OpenAI dispatching by model name; each entry is exc-or-value."""
    def dispatch(*, model: str, **kwargs):
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
    client.chat.completions.create = MagicMock(side_effect=dispatch)
    return client


class CompleteWithResilienceTests(unittest.TestCase):
    """Fixed 3-model chain: qwen-primary, deepseek-backup, glm-third."""

    def setUp(self) -> None:
        llm_client._reset_breaker_for_tests()
        llm_client._reset_alerts_for_tests()
        llm_client.reset_alert_sink()
        llm_client.reset_sync_ollama_factory()

        self._orig_model_chat = llm_client.MODEL_CHAT
        self._orig_chat_models = llm_client.AI_CHAT_MODELS
        self._orig_ollama = llm_client.OLLAMA_BASE_URL
        llm_client.MODEL_CHAT = "qwen-primary"
        llm_client.AI_CHAT_MODELS = ["qwen-primary", "deepseek-backup", "glm-third"]
        llm_client.OLLAMA_BASE_URL = ""  # default off; tests opt-in

        # No real sleeps in retry backoff.
        self._sleep_patch = patch("llm_client.time.sleep", MagicMock())
        self._sleep_patch.start()

        self.alerts: list[tuple[str, str, str]] = []
        llm_client.set_alert_sink(
            lambda title, summary, level: self.alerts.append((title, summary, level))
        )

    def tearDown(self) -> None:
        self._sleep_patch.stop()
        llm_client.MODEL_CHAT = self._orig_model_chat
        llm_client.AI_CHAT_MODELS = self._orig_chat_models
        llm_client.OLLAMA_BASE_URL = self._orig_ollama
        llm_client.reset_alert_sink()
        llm_client.reset_sync_ollama_factory()
        llm_client._reset_breaker_for_tests()
        llm_client._reset_alerts_for_tests()

    def _call(self, client, **kw):
        return llm_client.complete_with_resilience(
            client,
            model=kw.pop("model", "qwen-primary"),
            messages=[{"role": "user", "content": "hi"}],
            **kw,
        )

    # ── Case 1 ───────────────────────────────────────────────────────────────
    def test_1_happy_path_primary_success(self):
        resp_marker = SimpleNamespace(id="ok-1")
        client = _make_fake_client({"qwen-primary": [resp_marker]})

        result = self._call(client)

        self.assertIs(result, resp_marker)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(self.alerts, [], "happy path must not fire alerts")
        self.assertEqual(llm_client._breaker.failures, 0)

    # ── Case 2 ───────────────────────────────────────────────────────────────
    def test_2_retry_after_rate_limit(self):
        resp_marker = SimpleNamespace(id="ok-2")
        client = _make_fake_client({"qwen-primary": [_make_rate_limit(), resp_marker]})

        result = self._call(client)

        self.assertIs(result, resp_marker)
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertEqual(self.alerts, [], "in-model retry must not fire alerts")
        llm_client.time.sleep.assert_called()

    # ── Case 3 ───────────────────────────────────────────────────────────────
    def test_3_fallback_to_second_cloud_model(self):
        resp_marker = SimpleNamespace(id="ok-3")
        client = _make_fake_client({
            "qwen-primary": [_make_api_error(503)] * 3,
            "deepseek-backup": [resp_marker],
        })

        result = self._call(client, scene="audit")

        self.assertIs(result, resp_marker)
        self.assertEqual(len(self.alerts), 1, "degraded path fires one warning alert")
        title, summary, level = self.alerts[0]
        self.assertEqual(level, "warning")
        self.assertIn("降级", title)
        self.assertIn("audit", summary)
        self.assertEqual(llm_client._breaker.failures, 0)

    # ── Case 4 ───────────────────────────────────────────────────────────────
    def test_4_ollama_fallback_when_all_cloud_down(self):
        llm_client.OLLAMA_BASE_URL = "http://192.168.9.226:11434/v1"
        resp_marker = SimpleNamespace(id="ok-4")

        cloud = _make_fake_client({
            "qwen-primary":    [_make_api_error(503)] * 3,
            "deepseek-backup": [_make_api_error(503)] * 3,
            "glm-third":       [_make_api_error(503)] * 3,
        })
        ollama = _make_fake_client({"qwen-primary": [resp_marker]})
        llm_client.set_sync_ollama_factory(lambda: ollama)

        result = self._call(cloud, scene="compliance")

        self.assertIs(result, resp_marker)
        self.assertEqual(len(self.alerts), 1)
        title, _, level = self.alerts[0]
        self.assertEqual(level, "warning")
        self.assertIn("Ollama", title)

    # ── Case 5 ───────────────────────────────────────────────────────────────
    def test_5_total_failure_opens_breaker_and_alerts(self):
        llm_client.OLLAMA_BASE_URL = ""
        client = _make_fake_client({
            "qwen-primary":    [_make_api_error(503)] * 3,
            "deepseek-backup": [_make_api_error(503)] * 3,
            "glm-third":       [_make_api_error(503)] * 3,
        })

        with self.assertRaises(RuntimeError) as ctx:
            self._call(client, scene="ledger")

        self.assertIn("全部不可用", str(ctx.exception))
        self.assertEqual(llm_client._breaker.failures, 1)
        self.assertEqual(len(self.alerts), 1)
        self.assertEqual(self.alerts[0][2], "error")
        self.assertIn("ledger", self.alerts[0][1])

    # ── Case 6 ───────────────────────────────────────────────────────────────
    def test_6_open_breaker_rejects_immediately(self):
        llm_client._breaker.failures = llm_client._BREAKER_THRESHOLD
        llm_client._breaker.open_until = time.time() + 30

        client = _make_fake_client({"qwen-primary": [SimpleNamespace(id="unused")]})

        with self.assertRaises(RuntimeError) as ctx:
            self._call(client)

        self.assertIn("circuit breaker", str(ctx.exception))
        self.assertEqual(
            client.chat.completions.create.call_count, 0,
            "open breaker must not call the client",
        )

    # ── Case 7 ───────────────────────────────────────────────────────────────
    def test_7_breaker_resets_after_cooldown(self):
        llm_client._breaker.failures = llm_client._BREAKER_THRESHOLD
        llm_client._breaker.open_until = time.time() - 70  # already expired

        resp_marker = SimpleNamespace(id="ok-7")
        client = _make_fake_client({"qwen-primary": [resp_marker]})

        result = self._call(client)

        self.assertIs(result, resp_marker)
        self.assertEqual(llm_client._breaker.failures, 0, "success resets failure counter")

    # ── Case 8 ───────────────────────────────────────────────────────────────
    def test_8_alert_dedupe_within_60s(self):
        llm_client.OLLAMA_BASE_URL = ""
        behaviours: dict[str, list] = {
            "qwen-primary":    [_make_api_error(503)] * 6,
            "deepseek-backup": [_make_api_error(503)] * 6,
            "glm-third":       [_make_api_error(503)] * 6,
        }

        def dispatch(*, model: str, **kwargs):
            q = behaviours.get(model, [])
            if not q:
                raise APIError(message=f"empty {model}", request=MagicMock(), body=None)
            raise q.pop(0)

        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = MagicMock(side_effect=dispatch)

        for _ in range(2):
            with self.assertRaises(RuntimeError):
                self._call(client, scene="training")

        same_scene = [a for a in self.alerts if "training" in a[1]]
        self.assertEqual(
            len(same_scene), 1,
            f"expected exactly 1 dedupe'd alert; got {len(same_scene)}: {same_scene}",
        )


class TracedCompleteResilienceIntegrationTests(unittest.TestCase):
    """traced_complete now routes through complete_with_resilience and records
    the model that actually served the response (a fallback after degradation)."""

    def setUp(self) -> None:
        llm_client._reset_breaker_for_tests()
        llm_client._reset_alerts_for_tests()
        llm_client.reset_alert_sink()
        llm_client.set_alert_sink(lambda *a: None)

        self._orig_model_chat = llm_client.MODEL_CHAT
        self._orig_chat_models = llm_client.AI_CHAT_MODELS
        self._orig_ollama = llm_client.OLLAMA_BASE_URL
        llm_client.MODEL_CHAT = "qwen-primary"
        llm_client.AI_CHAT_MODELS = ["qwen-primary", "deepseek-backup"]
        llm_client.OLLAMA_BASE_URL = ""

        self._sleep_patch = patch("llm_client.time.sleep", MagicMock())
        self._sleep_patch.start()

        # NoopTracer that captures the recorded model.
        import llm_audit
        from skills.tracer import NoopTracer

        self.recorded: dict = {}
        captor = self  # noqa

        class _CaptureSpan:
            def record(self, **kw):
                captor.recorded.update(kw)

        class _CaptureTracer(NoopTracer):
            def sync_span(self_inner, **kwargs):
                from contextlib import contextmanager

                @contextmanager
                def _cm():
                    yield _CaptureSpan()
                return _cm()

        self._orig_tracer = llm_audit._tracer
        llm_audit.set_tracer(_CaptureTracer())

    def tearDown(self) -> None:
        import llm_audit
        llm_audit._tracer = self._orig_tracer
        self._sleep_patch.stop()
        llm_client.MODEL_CHAT = self._orig_model_chat
        llm_client.AI_CHAT_MODELS = self._orig_chat_models
        llm_client.OLLAMA_BASE_URL = self._orig_ollama
        llm_client.reset_alert_sink()
        llm_client._reset_breaker_for_tests()
        llm_client._reset_alerts_for_tests()

    def test_records_served_model_after_fallback(self):
        import llm_audit

        served = SimpleNamespace(
            id="resp",
            model="deepseek-backup",  # real string the server reports
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )
        client = _make_fake_client({
            "qwen-primary": [_make_api_error(503)] * 3,
            "deepseek-backup": [served],
        })

        # Unmapped scene → effective_model stays the caller's "qwen-primary",
        # so the fallback chain is exactly [qwen-primary, deepseek-backup].
        resp = llm_audit.traced_complete(
            client,
            scene="resilience_integration_unmapped",
            prompt_template_id="t.v1",
            model="qwen-primary",
            messages=[{"role": "user", "content": "hi"}],
            inject_few_shot=False,
        )

        self.assertIs(resp, served)
        self.assertEqual(
            self.recorded.get("model"), "deepseek-backup",
            "trace must record the fallback model that actually served",
        )


if __name__ == "__main__":
    unittest.main()
