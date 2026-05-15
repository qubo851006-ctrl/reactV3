"""Contract tests for the skill dispatcher.

These cover the wiring between classify → resolve → handle, plus the
fast_match short-circuit. Real LLM calls are mocked.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from skills.base import Classification, SkillContext, done_event, chunk_event  # noqa: E402
from skills.dispatcher import Dispatcher  # noqa: E402


class _StubSkill:
    """Minimal Skill for routing tests."""

    def __init__(self, intent: str, *, description: str = "stub",
                 next_stage: str | None = None,
                 extra_fields: tuple[str, ...] = (),
                 reply: str = "stub-reply",
                 fast_match_kw: str | None = None):
        self.intent = intent
        self.description = description
        self.next_stage = next_stage
        self.extra_fields = extra_fields
        self._reply = reply
        self._fast_kw = fast_match_kw
        self.handle_called_with: SkillContext | None = None

    def fast_match(self, message: str) -> bool:
        return bool(self._fast_kw) and self._fast_kw in message

    async def handle(self, ctx: SkillContext) -> AsyncIterator[dict]:
        self.handle_called_with = ctx
        yield done_event(reply=self._reply, next_stage=self.next_stage or "idle")


def _mock_openai_returning(intent_json: dict) -> MagicMock:
    """Build an AsyncOpenAI mock whose chat.completions.create returns the JSON."""
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json.dumps(intent_json)))]
    completion.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    create = AsyncMock(return_value=completion)
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = create
    return client


def _ctx_factory(classification: Classification) -> SkillContext:
    """Build a SkillContext for tests — most fields are not exercised."""
    return SkillContext(
        user=MagicMock(id=1),
        message="dummy",
        history=[],
        classification=classification,
        llm_client=MagicMock(),
        selected_chat_model="model-x",
        selected_vision_model="model-v",
        use_kb=False,
        kb_conversation_id="",
        session_id="sess_test",
        tracer=None,  # real dispatcher passes its own tracer; not used in handle
    )


class DispatcherDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_real_discovery_finds_all_business_skills(self):
        d = Dispatcher()
        intents = {s.intent for s in d.skills}
        # All 7 fixed-reply intents
        for intent in (
            "download_training_excel",
            "download_ledger_excel",
            "download_compliance_excel",
            "waiting_files",
            "waiting_ledger_files",
            "waiting_auth_file",
            "waiting_compliance_file",
        ):
            self.assertIn(intent, intents, f"missing fixed-reply intent {intent}")
        # The other production skills
        for intent in ("query_company", "debt_recovery_assessment",
                        "model_status", "kb_query", "other"):
            self.assertIn(intent, intents, f"missing skill {intent}")

    def test_classifier_metas_exclude_fallback(self):
        d = Dispatcher()
        intents = {m.intent for m in d.metas_for_classifier()}
        self.assertNotIn("other", intents)
        self.assertIn("query_company", intents)

    def test_extra_fields_propagate_to_classifier_meta(self):
        d = Dispatcher()
        meta_by_intent = {m.intent: m for m in d.metas_for_classifier()}
        self.assertEqual(meta_by_intent["query_company"].extra_fields, ("company",))
        self.assertEqual(
            meta_by_intent["debt_recovery_assessment"].extra_fields,
            ("company", "claim_amount"),
        )


class DispatcherRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_routes_to_classified_intent(self):
        a = _StubSkill("alpha", reply="A")
        b = _StubSkill("beta", reply="B")
        fallback = _StubSkill("other", reply="F")
        d = Dispatcher(skills=[a, b, fallback])

        client = _mock_openai_returning({"intent": "beta"})
        events = []
        async for ev in d.dispatch(_ctx_factory, client, "hi"):
            events.append(ev)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["reply"], "B")
        self.assertIsNotNone(b.handle_called_with)
        self.assertIsNone(a.handle_called_with)
        self.assertIsNone(fallback.handle_called_with)

    async def test_dispatch_falls_back_on_unknown_intent(self):
        a = _StubSkill("alpha")
        fallback = _StubSkill("other", reply="fallback-reply")
        d = Dispatcher(skills=[a, fallback])

        client = _mock_openai_returning({"intent": "ghost"})
        events = [ev async for ev in d.dispatch(_ctx_factory, client, "x")]
        self.assertEqual(events[0]["reply"], "fallback-reply")
        self.assertIsNotNone(fallback.handle_called_with)

    async def test_fast_match_skips_classifier(self):
        fast = _StubSkill("fastpath", reply="FAST", fast_match_kw="ping")
        other = _StubSkill("other", reply="other")
        d = Dispatcher(skills=[fast, other])

        # Classifier should never be called — pass a client that explodes if it is.
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=AssertionError("classifier should not be called"),
        )

        events = [ev async for ev in d.dispatch(_ctx_factory, client, "say ping back")]
        self.assertEqual(events[0]["reply"], "FAST")

    async def test_classify_only_uses_other_on_invalid_json(self):
        fallback = _StubSkill("other")
        d = Dispatcher(skills=[fallback])

        bad = MagicMock()
        bad.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(message=MagicMock(content="not json"))],
                usage=None,
            ),
        )
        cls = await d.classify_only(bad, "anything")
        self.assertEqual(cls.intent, "other")


class FixedReplySkillIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_fixed_reply_emits_canonical_done_event(self):
        from skills.implementations.fixed_reply import SKILLS as FIXED
        for skill in FIXED:
            ctx = _ctx_factory(Classification(intent=skill.intent))
            events = [ev async for ev in skill.handle(ctx)]
            self.assertEqual(len(events), 1, f"{skill.intent} yielded {len(events)} events")
            ev = events[0]
            self.assertEqual(ev["type"], "done")
            self.assertEqual(ev["reply"], skill.reply)
            self.assertEqual(ev["next_stage"], skill.next_stage)


class ModelStatusSkillTests(unittest.IsolatedAsyncioTestCase):
    async def test_fast_match_keywords(self):
        from skills.implementations.model_status import SKILL as MS
        self.assertTrue(MS.fast_match("你是什么模型"))
        self.assertTrue(MS.fast_match("现在是什么模型？"))
        self.assertTrue(MS.fast_match("  当前 模型 "))
        self.assertFalse(MS.fast_match("帮我整理案件"))

    async def test_handle_reports_both_models(self):
        from skills.implementations.model_status import SKILL as MS
        ctx = _ctx_factory(Classification(intent="model_status"))
        ctx = SkillContext(**{**ctx.__dict__,
                              "selected_chat_model": "qwen-test",
                              "selected_vision_model": "vision-test"})
        events = [ev async for ev in MS.handle(ctx)]
        self.assertEqual(len(events), 1)
        self.assertIn("qwen-test", events[0]["reply"])
        self.assertIn("vision-test", events[0]["reply"])


if __name__ == "__main__":
    unittest.main()
