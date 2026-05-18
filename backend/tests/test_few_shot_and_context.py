"""P1-2 backend tests: trace_id collection + few-shot injection.

These tests run against a SQLite tempfile (no PG dependency) so CI doesn't
need network access. Tests cover:
- collect_traces captures every span's trace_id
- vision scenes are skipped by few-shot
- examples are deduped by input_hash and rendered into a system prefix
- traced_complete prepends the prefix when examples exist
- invalidate_cache forces a re-query
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from llm_audit.db import AuditBase
import llm_audit.models  # noqa: F401  — registers LLMTrace on AuditBase


def _isolated_factory(tmp_db: Path):
    engine = create_engine(
        f"sqlite:///{tmp_db}",
        connect_args={"check_same_thread": False},
    )
    AuditBase.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


class _IsolatedTracerMixin:
    """Set up a per-test PersistentTracer + SQLite + clear caches."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_db = Path(self._tmp.name) / "audit.db"
        self._engine, self.SessionLocal = _isolated_factory(tmp_db)

        from llm_audit.tracer import PersistentTracer
        from llm_audit.db import set_audit_engine, reset_audit_engine
        import llm_audit
        from llm_audit import few_shot

        # Inject our SQLite at the module level so few_shot.fetch_examples
        # (which calls get_audit_session_factory) sees the same DB as the
        # tracer.
        self._reset_audit_engine = reset_audit_engine
        set_audit_engine(self._engine, self.SessionLocal)

        self._orig_tracer = llm_audit._tracer
        llm_audit.set_tracer(PersistentTracer(session_factory=self.SessionLocal))
        few_shot.invalidate_cache()

    def tearDown(self):
        import llm_audit
        from llm_audit import few_shot
        llm_audit._tracer = self._orig_tracer
        few_shot.invalidate_cache()
        # Reset module-level engine so subsequent tests don't see ours.
        self._reset_audit_engine()
        self._engine.dispose()
        self._tmp.cleanup()


class CollectTracesTests(_IsolatedTracerMixin, unittest.TestCase):
    def test_bucket_captures_ids_from_traced_complete(self):
        from llm_audit import traced_complete
        from llm_audit.context import collect_traces

        # Mock OpenAI sync client.
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="ok"))]
        completion.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
        client = MagicMock()
        client.chat.completions.create.return_value = completion

        with collect_traces() as bucket:
            for _ in range(3):
                traced_complete(
                    client,
                    scene="scene_x",
                    prompt_template_id="x.v1",
                    model="m",
                    messages=[{"role": "user", "content": "hi"}],
                    inject_few_shot=False,
                )

        self.assertEqual(len(bucket.ids), 3)
        for tid in bucket.ids:
            self.assertEqual(len(tid), 24)  # secrets.token_hex(12)

    def test_nested_collect_traces_isolates_scopes(self):
        from llm_audit import traced_complete
        from llm_audit.context import collect_traces

        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="ok"))]
        completion.usage = None
        client = MagicMock()
        client.chat.completions.create.return_value = completion

        with collect_traces() as outer:
            traced_complete(client, scene="s", prompt_template_id="x", model="m",
                            messages=[{"role": "user", "content": "a"}],
                            inject_few_shot=False)
            with collect_traces() as inner:
                traced_complete(client, scene="s", prompt_template_id="x", model="m",
                                messages=[{"role": "user", "content": "b"}],
                                inject_few_shot=False)
            traced_complete(client, scene="s", prompt_template_id="x", model="m",
                            messages=[{"role": "user", "content": "c"}],
                            inject_few_shot=False)

        # Outer should see only its own 2 calls; inner saw 1.
        self.assertEqual(len(outer.ids), 2)
        self.assertEqual(len(inner.ids), 1)
        # No id overlap.
        self.assertFalse(set(outer.ids) & set(inner.ids))


class FewShotEngineTests(_IsolatedTracerMixin, unittest.TestCase):
    def _seed_feedback(self, scene: str, count: int = 3):
        """Insert N accepted+edited rows for `scene` so few-shot can find them."""
        from datetime import datetime, timezone
        from llm_audit.models import LLMTrace
        with self.SessionLocal() as s:
            for i in range(count):
                s.add(LLMTrace(
                    trace_id=f"seed-{scene}-{i}",
                    scene=scene,
                    prompt_template_id=f"{scene}.v1",
                    model="m",
                    input_hash=f"hash-{i}",
                    input_preview=f"input #{i}",
                    input_text=f'[{{"role":"user","content":"input #{i}"}}]',
                    output_text=f'{{"raw": {i}}}',
                    tokens_in=10, tokens_out=2, duration_ms=5,
                    user_id=1, session_id="s",
                    accepted=True,
                    edited_to=f'{{"corrected": {i}}}',
                    created_at=datetime.now(timezone.utc),
                ))
            s.commit()

    def test_vision_scenes_are_skipped(self):
        from llm_audit.few_shot import fetch_examples, is_vision_scene

        self.assertTrue(is_vision_scene("vision_analyze_image"))
        self.assertTrue(is_vision_scene("ledger.vision_ocr_page"))
        self.assertFalse(is_vision_scene("extract_judgment_fields"))
        self.assertEqual(fetch_examples("vision_analyze_image"), [])

    def test_examples_returned_when_feedback_exists(self):
        from llm_audit.few_shot import fetch_examples
        self._seed_feedback("extract_judgment_fields", count=3)
        examples = fetch_examples("extract_judgment_fields")
        self.assertEqual(len(examples), 3)
        for ex in examples:
            self.assertIn("input_text", ex)
            self.assertIn("edited_to", ex)
            self.assertIn("corrected", ex["edited_to"])

    def test_dedup_by_input_hash(self):
        """Two rows with same input_hash collapse to one example."""
        from datetime import datetime, timezone
        from llm_audit.few_shot import fetch_examples, invalidate_cache
        from llm_audit.models import LLMTrace
        invalidate_cache()
        with self.SessionLocal() as s:
            for i in range(2):
                s.add(LLMTrace(
                    trace_id=f"dup-{i}", scene="extract_business_fields",
                    input_hash="SAME", input_preview="p",
                    input_text='[{"role":"user","content":"p"}]',
                    output_text="{}", tokens_in=0, tokens_out=0, duration_ms=0,
                    accepted=True, edited_to=f"v{i}",
                    created_at=datetime.now(timezone.utc),
                ))
            s.commit()
        examples = fetch_examples("extract_business_fields")
        self.assertEqual(len(examples), 1)

    def test_compose_system_prefix_renders_examples(self):
        from llm_audit.few_shot import compose_system_prefix

        prefix = compose_system_prefix([
            {"input_text": '[{"role":"user","content":"案件 X"}]',
             "edited_to": '{"案由": "买卖合同纠纷"}'},
        ])
        assert prefix is not None
        self.assertIn("买卖合同纠纷", prefix)
        self.assertIn("案件 X", prefix)
        self.assertIn("示例", prefix)

    def test_compose_system_prefix_returns_none_when_empty(self):
        from llm_audit.few_shot import compose_system_prefix
        self.assertIsNone(compose_system_prefix([]))

    def test_traced_complete_prepends_few_shot_prefix(self):
        from llm_audit import traced_complete
        self._seed_feedback("extract_litigation_fields", count=2)

        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="resp"))]
        completion.usage = None
        client = MagicMock()
        client.chat.completions.create.return_value = completion

        original_messages = [{"role": "user", "content": "现在请处理新案件"}]
        traced_complete(
            client,
            scene="extract_litigation_fields",
            prompt_template_id="ledger.suosostate.v1",
            model="m",
            messages=original_messages,
        )

        call_kwargs = client.chat.completions.create.call_args.kwargs
        sent_messages = call_kwargs["messages"]
        self.assertEqual(sent_messages[0]["role"], "system")
        self.assertIn("示例", sent_messages[0]["content"])
        self.assertEqual(sent_messages[-1], original_messages[0])
        # Original list is not mutated.
        self.assertEqual(original_messages, [{"role": "user", "content": "现在请处理新案件"}])

    def test_inject_few_shot_false_skips_injection(self):
        from llm_audit import traced_complete
        self._seed_feedback("extract_judgment_fields", count=2)

        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="r"))]
        completion.usage = None
        client = MagicMock()
        client.chat.completions.create.return_value = completion

        original = [{"role": "user", "content": "x"}]
        traced_complete(
            client,
            scene="extract_judgment_fields",
            prompt_template_id="ledger.judgment.v1",
            model="m",
            messages=original,
            inject_few_shot=False,
        )
        sent = client.chat.completions.create.call_args.kwargs["messages"]
        self.assertEqual(sent, original)

    def test_cache_invalidation_picks_up_new_feedback(self):
        from llm_audit.few_shot import fetch_examples, invalidate_cache
        scene = "compliance_extract"
        # First call: empty.
        self.assertEqual(fetch_examples(scene), [])
        # Add a feedback row.
        self._seed_feedback(scene, count=1)
        # Without invalidation, cache still returns empty list.
        self.assertEqual(fetch_examples(scene), [])
        # After invalidation, the new row appears.
        invalidate_cache(scene)
        examples = fetch_examples(scene)
        self.assertEqual(len(examples), 1)


if __name__ == "__main__":
    unittest.main()
