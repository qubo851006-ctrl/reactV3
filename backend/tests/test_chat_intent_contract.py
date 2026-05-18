"""Chat intent classification contract — protects against silent drift.

The dispatcher routes by `Classification.intent`. If the classifier ever
starts misroute things (because we changed the prompt, swapped the
model, or added a new skill that hijacks a pattern), users see broken
behaviour silently — no exception, just the wrong upload form.

These tests pin the contract by:
1. Asserting the registered skills include exactly the intents we expect.
2. Asserting that fixed-reply skills emit the canonical (reply, next_stage)
   pair the frontend relies on.
3. Asserting common user phrasings classify into the right intent under a
   mocked LLM, so we catch dispatcher routing regressions even if a real
   classifier change slips through.

The tests use a fake AsyncOpenAI that returns canned JSON — they do NOT
hit the real classifier model. That's intentional: this file is a
contract test, not a model-quality benchmark.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from skills.base import SkillContext
from skills.dispatcher import Dispatcher


def _fake_async_openai(intent_json: dict) -> MagicMock:
    """Build an AsyncOpenAI mock whose chat.completions.create returns
    the given JSON wrapped in the OpenAI completion shape."""
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=json.dumps(intent_json)))]
    completion.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=completion)
    return client


def _ctx_factory(classification):
    """Stand-in SkillContext for dispatcher tests — fields skills don't
    consume in the assertions below stay as MagicMocks."""
    return SkillContext(
        user=MagicMock(id=1),
        message="",
        history=[],
        classification=classification,
        llm_client=MagicMock(),
        selected_chat_model="m",
        selected_vision_model="v",
        use_kb=False,
        kb_conversation_id="",
        session_id="sess_x",
        tracer=None,
    )


class RegisteredIntentsContractTests(unittest.TestCase):
    """Skill set the frontend depends on."""

    def test_all_canonical_intents_present(self):
        d = Dispatcher()
        intents = {s.intent for s in d.skills}
        expected = {
            "download_training_excel",
            "download_ledger_excel",
            "download_compliance_excel",
            "waiting_files",
            "waiting_ledger_files",
            "waiting_auth_file",
            "waiting_compliance_file",
            "query_company",
            "debt_recovery_assessment",
            "model_status",
            "kb_query",
            "other",
        }
        missing = expected - intents
        self.assertFalse(missing, f"frontend relies on these intents: missing={missing}")

    def test_extra_fields_contract_for_qcc_skills(self):
        """query_company needs `company`; debt_recovery_assessment needs
        `company` and `claim_amount`. If these change, the classifier
        prompt stops asking for them and the QCC call breaks."""
        d = Dispatcher()
        meta = {m.intent: m for m in d.metas_for_classifier()}
        self.assertEqual(meta["query_company"].extra_fields, ("company",))
        self.assertEqual(
            meta["debt_recovery_assessment"].extra_fields,
            ("company", "claim_amount"),
        )


class FixedReplyNextStageContractTests(unittest.IsolatedAsyncioTestCase):
    """The frontend reacts on `next_stage` to open the right uploader.
    These pairs must NOT drift silently."""

    EXPECTED = [
        ("waiting_files", "waiting_files"),
        ("waiting_ledger_files", "waiting_ledger_files"),
        ("waiting_auth_file", "waiting_auth_file"),
        ("waiting_compliance_file", "waiting_compliance_file"),
        ("download_training_excel", "download_training_excel"),
        ("download_ledger_excel", "download_ledger_excel"),
        ("download_compliance_excel", "download_compliance_excel"),
    ]

    async def test_each_fixed_reply_skill_emits_canonical_next_stage(self):
        from skills.base import Classification
        from skills.implementations.fixed_reply import SKILLS as FIXED
        by_intent = {s.intent: s for s in FIXED}
        for intent, expected_stage in self.EXPECTED:
            skill = by_intent.get(intent)
            self.assertIsNotNone(skill, f"fixed_reply skill {intent} disappeared")
            ctx = _ctx_factory(Classification(intent=intent))
            events = [ev async for ev in skill.handle(ctx)]
            self.assertEqual(len(events), 1, f"{intent} yielded {len(events)} events")
            self.assertEqual(events[0]["type"], "done")
            self.assertEqual(
                events[0]["next_stage"], expected_stage,
                f"{intent} → next_stage drifted: got {events[0]['next_stage']!r}, want {expected_stage!r}",
            )
            self.assertTrue(events[0]["reply"], f"{intent} must have a non-empty reply")


class ClassifierRoutingTests(unittest.IsolatedAsyncioTestCase):
    """Given a classifier verdict, does the dispatcher pick the right skill
    and pass extra fields through?

    We test the routing wire, not the LLM's classification quality. The
    LLM is mocked to return canned JSON; we then check that `_resolve`
    picks the expected skill, and `classify_only` extracts extra fields.
    """

    async def test_classifier_extracts_intent_and_company(self):
        d = Dispatcher()
        client = _fake_async_openai({"intent": "query_company", "company": "示例科技有限公司"})
        cls = await d.classify_only(client, "查一下示例科技公司")
        self.assertEqual(cls.intent, "query_company")
        self.assertEqual(cls.company, "示例科技有限公司")

    async def test_classifier_extracts_claim_amount(self):
        d = Dispatcher()
        client = _fake_async_openai({
            "intent": "debt_recovery_assessment",
            "company": "甲公司",
            "claim_amount": 1500000,
        })
        cls = await d.classify_only(client, "甲公司欠我们 150 万,该不该追?")
        self.assertEqual(cls.intent, "debt_recovery_assessment")
        self.assertEqual(cls.company, "甲公司")
        self.assertEqual(cls.claim_amount, 1500000.0)

    async def test_unknown_intent_falls_back_to_other(self):
        d = Dispatcher()
        client = _fake_async_openai({"intent": "this_intent_does_not_exist"})
        cls = await d.classify_only(client, "x")
        # classify coerces unknown intents to 'other' (defends against LLM
        # hallucinating intent names that no skill knows about)
        self.assertEqual(cls.intent, "other")

    async def test_classifier_malformed_json_falls_back(self):
        d = Dispatcher()
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="not even close to json"))]
        completion.usage = None
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=completion)
        cls = await d.classify_only(client, "x")
        self.assertEqual(cls.intent, "other")

    async def test_dispatch_routes_each_intent_to_a_skill(self):
        """For every intent the classifier can produce, the dispatcher
        must resolve a skill (not raise KeyError)."""
        from skills.base import Classification
        d = Dispatcher()
        all_intents = {s.intent for s in d.skills}
        for intent in all_intents:
            skill = d._resolve(intent)  # noqa: SLF001 — testing the routing primitive
            self.assertEqual(skill.intent, intent, f"resolve({intent!r}) returned wrong skill")
        # Unknown intent must fall back to the 'other' fallback, never KeyError.
        fallback = d._resolve("definitely_made_up_intent")  # noqa: SLF001
        self.assertEqual(fallback.intent, "other")

    async def test_next_stage_filter_rejects_hallucinated_stages(self):
        """The classifier prompt allows next_stage as a free-text field for
        general chat. Hallucinated stages must be discarded by classify_only."""
        d = Dispatcher()
        client = _fake_async_openai({
            "intent": "other",
            "next_stage": "made_up_stage_xyz",  # not in ACTIONABLE
        })
        cls = await d.classify_only(client, "x")
        self.assertEqual(cls.intent, "other")
        self.assertIsNone(cls.next_stage)  # bad stage gets cleared


class ModelStatusFastPathTests(unittest.IsolatedAsyncioTestCase):
    """The "you are what model" question must NEVER hit the classifier."""

    async def test_fast_match_bypasses_llm(self):
        d = Dispatcher()
        client = MagicMock()
        # Configure the mock to ASSERT if create is called — fast_match
        # should mean the LLM is never invoked for this message.
        client.chat.completions.create = AsyncMock(
            side_effect=AssertionError("classifier should not run for model status query"),
        )
        events = []
        async for ev in d.dispatch(_ctx_factory, client, "你是什么模型"):
            events.append(ev)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "done")
        # The reply mentions both models
        self.assertIn("文字模型", events[0]["reply"])
        self.assertIn("图像模型", events[0]["reply"])


if __name__ == "__main__":
    unittest.main()
