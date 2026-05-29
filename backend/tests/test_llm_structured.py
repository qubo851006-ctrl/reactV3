"""Tests for strict structured-output extraction (N2).

Coverage (8 cases for extract_structured + 4 for call_llm_structured = 12):
  extract_structured:
    1. Happy path: clean JSON parses into model
    2. Markdown code fence wrap: ```json {...} ``` still parses
    3. Narrative prefix + JSON: "结果: { ... }" still parses
    4. JSON embedded in surrounding text: "....{ ... }...." extracts
    5. Missing required field: returns fallback (NOT a half-valid model)
    6. Wrong type for field: returns fallback
    7. Extra fields beyond schema: parses successfully (lenient by default)
    8. Truncated / invalid JSON: returns fallback
    9. Empty/None input: returns fallback
   10. Non-object root (array / scalar): returns fallback

  call_llm_structured:
   11. Provider rejects response_format -> auto-retries without it
   12. Total LLM failure returns fallback (does not propagate)

This is the N2 layer — every failure mode that previously polluted business
columns with raw JSON text is now contained by extract_structured + the
LLMClient call path.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import BaseModel

import llm_client
from utils.llm_extract import extract_structured


# ── Schemas used across the test cases ──────────────────────────────────────

class TrainingMeta(BaseModel):
    """Mirrors the real "培训元数据" abstraction (topic / category / hours)."""
    topic: str
    category: str
    hours: int


class StrictMeta(BaseModel):
    """Used for the extra-fields tolerance test."""
    topic: str
    category: str

    model_config = {"extra": "allow"}  # default Pydantic v2; explicit for clarity


# ── extract_structured tests ────────────────────────────────────────────────

class ExtractStructuredTests(unittest.TestCase):

    # Case 1
    def test_1_happy_path_clean_json(self):
        raw = '{"topic": "信息安全", "category": "合规培训", "hours": 4}'
        out = extract_structured(raw, TrainingMeta, scene="t1")
        self.assertIsInstance(out, TrainingMeta)
        self.assertEqual(out.topic, "信息安全")
        self.assertEqual(out.category, "合规培训")
        self.assertEqual(out.hours, 4)

    # Case 2
    def test_2_markdown_fence_wrapped(self):
        raw = '```json\n{"topic": "信息安全", "category": "合规培训", "hours": 4}\n```'
        out = extract_structured(raw, TrainingMeta, scene="t2")
        self.assertIsInstance(out, TrainingMeta)
        self.assertEqual(out.category, "合规培训")

    # Case 3
    def test_3_narrative_prefix_then_json(self):
        raw = '结果: {"topic": "数据治理", "category": "技术培训", "hours": 8}'
        out = extract_structured(raw, TrainingMeta, scene="t3")
        self.assertIsInstance(out, TrainingMeta)
        self.assertEqual(out.topic, "数据治理")

    # Case 4
    def test_4_json_embedded_in_surrounding_text(self):
        raw = (
            "根据您的输入,我识别到以下信息:"
            '{"topic": "反欺诈培训", "category": "合规培训", "hours": 6}'
            "如有疑问请人工核对。"
        )
        out = extract_structured(raw, TrainingMeta, scene="t4")
        self.assertIsInstance(out, TrainingMeta)
        self.assertEqual(out.topic, "反欺诈培训")

    # Case 5 — THE primary bug class this layer prevents
    def test_5_missing_required_field_returns_fallback(self):
        # 关键场景:小模型只吐 topic 和 category,漏掉 hours
        # 业务方拿到半截 dict 然后字符串化,就会把"整段 JSON"写入"hours"
        # 这里必须返回 fallback,绝不允许半截对象流出
        raw = '{"topic": "信息安全", "category": "合规培训"}'
        out = extract_structured(raw, TrainingMeta, fallback=None, scene="t5")
        self.assertIsNone(out)

    # Case 6
    def test_6_wrong_type_returns_fallback(self):
        # hours 应该是 int,LLM 吐了字符串
        raw = '{"topic": "信息安全", "category": "合规培训", "hours": "四个课时"}'
        out = extract_structured(raw, TrainingMeta, fallback=None, scene="t6")
        # NB: Pydantic v2 will try to coerce "四个课时" -> int -> fails -> fallback
        self.assertIsNone(out)

    # Case 7
    def test_7_extra_fields_still_parse(self):
        # 额外字段不是污染:Pydantic 默认忽略多余字段
        raw = (
            '{"topic": "数据治理", "category": "技术培训", "hours": 8, '
            '"trainer": "李工", "venue": "北京"}'
        )
        out = extract_structured(raw, TrainingMeta, scene="t7")
        self.assertIsInstance(out, TrainingMeta)
        self.assertEqual(out.hours, 8)

    # Case 8
    def test_8_truncated_json_returns_fallback(self):
        raw = '{"topic": "信息安全", "category": "合规培训", "ho'  # 截断
        out = extract_structured(raw, TrainingMeta, fallback=None, scene="t8")
        self.assertIsNone(out)

    # Case 9
    def test_9_empty_and_none_input(self):
        for raw in (None, "", "   \n  \t"):
            with self.subTest(raw=raw):
                out = extract_structured(raw, TrainingMeta, fallback=None, scene="t9")
                self.assertIsNone(out)

    # Case 10
    def test_10_non_object_root_returns_fallback(self):
        # LLM 吐了数组或标量
        for raw in (
            '["a", "b"]',
            '"just a string"',
            '42',
        ):
            with self.subTest(raw=raw):
                out = extract_structured(raw, TrainingMeta, fallback=None, scene="t10")
                self.assertIsNone(out)


# ── call_llm_structured tests ───────────────────────────────────────────────

def _fake_completion(content: str) -> SimpleNamespace:
    """Mimic openai.ChatCompletion shape just enough for content access."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class CallLlmStructuredTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        llm_client._reset_breaker_for_tests()
        llm_client._reset_alerts_for_tests()
        llm_client.reset_alert_sink()
        llm_client.reset_client_factory()

        self._orig_model_chat = llm_client.MODEL_CHAT
        self._orig_chat_models = llm_client.AI_CHAT_MODELS
        self._orig_ollama = llm_client.OLLAMA_BASE_URL
        llm_client.MODEL_CHAT = "qwen-primary"
        llm_client.AI_CHAT_MODELS = ["qwen-primary"]
        llm_client.OLLAMA_BASE_URL = ""

        self._orig_sleep = llm_client.asyncio.sleep
        llm_client.asyncio.sleep = AsyncMock()

    def tearDown(self) -> None:
        llm_client.MODEL_CHAT = self._orig_model_chat
        llm_client.AI_CHAT_MODELS = self._orig_chat_models
        llm_client.OLLAMA_BASE_URL = self._orig_ollama
        llm_client.asyncio.sleep = self._orig_sleep
        llm_client.reset_alert_sink()
        llm_client.reset_client_factory()
        llm_client._reset_breaker_for_tests()
        llm_client._reset_alerts_for_tests()

    # Case 11
    async def test_11_provider_rejects_json_mode_retries_without(self):
        """First call (with response_format=json_object) fails as if the model
        provider doesn't support it; helper transparently retries without it
        and succeeds."""
        attempts: list[dict] = []

        async def dispatch(*, model: str, **kwargs):
            attempts.append(kwargs)
            if "response_format" in kwargs:
                # Simulate "model does not support response_format" style error
                raise ValueError("model does not support response_format json_object")
            return _fake_completion('{"topic": "x", "category": "y", "hours": 1}')

        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=dispatch)
        llm_client.set_client_factory(lambda **kwargs: client)

        out = await llm_client.call_llm_structured(
            [{"role": "user", "content": "hi"}],
            TrainingMeta,
            scene="t11",
            max_retries=1,  # keep test fast
        )

        self.assertIsInstance(out, TrainingMeta)
        # First attempt had response_format, retry path did not.
        self.assertTrue(any("response_format" in a for a in attempts))
        self.assertTrue(any("response_format" not in a for a in attempts))

    # Case 12
    async def test_12_total_failure_returns_fallback_not_raise(self):
        """call_llm_structured must SWALLOW the RuntimeError from the underlying
        layer and return fallback — business code should never see a None or
        a raised error mixed together."""
        from openai import APIError

        def fail_factory(**kwargs):
            client = MagicMock()
            client.chat = MagicMock()
            client.chat.completions = MagicMock()
            async def always_fail(*, model: str, **kw):
                err = APIError(message="boom", request=MagicMock(), body=None)
                err.status_code = 503
                raise err
            client.chat.completions.create = AsyncMock(side_effect=always_fail)
            return client

        llm_client.set_client_factory(fail_factory)

        sentinel = TrainingMeta(topic="fb", category="fb", hours=0)
        out = await llm_client.call_llm_structured(
            [{"role": "user", "content": "hi"}],
            TrainingMeta,
            scene="t12",
            fallback=sentinel,
            max_retries=1,
        )

        self.assertIs(out, sentinel)


if __name__ == "__main__":
    unittest.main()
