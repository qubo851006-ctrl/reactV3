"""Persistent LLMTracer + trace query API tests."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


def _isolated_session_factory(tmp_db: Path):
    """Build a fresh engine + SessionLocal pointed at a tempfile SQLite DB,
    create only the llm_traces table on it. Returns (engine, SessionLocal);
    caller MUST dispose the engine in tearDown so Windows can unlink the file.

    After the P0-1 split, llm_traces lives on AuditBase (independent of the
    main app's Base), so we only create_all on AuditBase here.
    """
    from llm_audit.db import AuditBase
    import llm_audit.models  # noqa: F401 — registers LLMTrace on AuditBase

    engine = create_engine(
        f"sqlite:///{tmp_db}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _wal(conn, _rec):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")

    AuditBase.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


class PersistentTracerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_db = Path(self._tmp.name) / "audit_test.db"
        self._engine, self.SessionLocal = _isolated_session_factory(tmp_db)

    def tearDown(self):
        self._engine.dispose()
        self._tmp.cleanup()

    async def test_async_span_persists_full_call_record(self):
        from llm_audit.tracer import PersistentTracer
        from llm_audit.models import LLMTrace

        tracer = PersistentTracer(session_factory=self.SessionLocal)
        usage = MagicMock(prompt_tokens=42, completion_tokens=11)
        async with tracer.span(
            "extract_case_fields", user_id=7, session_id="sess_x",
        ) as span:
            span.record(
                model="qwen-test",
                input_messages=[{"role": "user", "content": "诉讼材料"}],
                output_text='{"案由": "合同纠纷"}',
                usage=usage,
                prompt_template_id="ledger.suosostate.v1",
            )

        with self.SessionLocal() as db:
            row = db.execute(select(LLMTrace)).scalar_one()
            self.assertEqual(row.scene, "extract_case_fields")
            self.assertEqual(row.user_id, 7)
            self.assertEqual(row.session_id, "sess_x")
            self.assertEqual(row.model, "qwen-test")
            self.assertEqual(row.tokens_in, 42)
            self.assertEqual(row.tokens_out, 11)
            self.assertEqual(row.prompt_template_id, "ledger.suosostate.v1")
            self.assertIn("合同纠纷", row.output_text)
            self.assertIn("诉讼材料", row.input_text)
            self.assertIn("诉讼材料", row.input_preview)
            self.assertEqual(len(row.input_hash), 64)
            self.assertIsNone(row.error)
            self.assertGreaterEqual(row.duration_ms, 0)

    async def test_span_records_error_and_re_raises(self):
        from llm_audit.tracer import PersistentTracer
        from llm_audit.models import LLMTrace

        tracer = PersistentTracer(session_factory=self.SessionLocal)
        with self.assertRaises(RuntimeError):
            async with tracer.span("intent_classify") as span:
                span.record(model="x", input_messages=[{"role": "user", "content": "hi"}])
                raise RuntimeError("upstream blew up")

        with self.SessionLocal() as db:
            row = db.execute(select(LLMTrace)).scalar_one()
            self.assertIn("upstream blew up", row.error)
            self.assertEqual(row.scene, "intent_classify")

    def test_sync_span_works_for_sync_call_sites(self):
        from llm_audit.tracer import PersistentTracer
        from llm_audit.models import LLMTrace

        tracer = PersistentTracer(session_factory=self.SessionLocal)
        with tracer.sync_span("ledger.judgment", user_id=3) as span:
            span.record(
                model="m1",
                input_messages=[{"role": "user", "content": "判决书全文"}],
                output_text='{"金额": 100}',
                prompt_template_id="ledger.judgment.v1",
            )

        with self.SessionLocal() as db:
            row = db.execute(select(LLMTrace)).scalar_one()
            self.assertEqual(row.user_id, 3)
            self.assertEqual(row.prompt_template_id, "ledger.judgment.v1")

    def test_persistence_failure_does_not_break_call_site(self):
        from llm_audit.tracer import PersistentTracer

        # Session factory that raises on commit — simulates DB outage.
        broken = MagicMock()
        broken_session = MagicMock()
        broken_session.commit.side_effect = RuntimeError("db gone")
        broken.return_value = broken_session
        tracer = PersistentTracer(session_factory=broken)

        # The span exits cleanly even though _persist explodes.
        with tracer.sync_span("scene_x") as span:
            span.record(model="m")
        # No assertion needed — the test passes if no exception escapes.


class TracedCompleteHelperTests(unittest.TestCase):
    """Verify ledger_helpers._traced_complete records via the global tracer."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_db = Path(self._tmp.name) / "audit_test.db"
        self._engine, self.SessionLocal = _isolated_session_factory(tmp_db)

        from llm_audit.tracer import PersistentTracer
        import llm_audit
        self._original_tracer = llm_audit._tracer
        llm_audit.set_tracer(PersistentTracer(session_factory=self.SessionLocal))

    def tearDown(self):
        import llm_audit
        llm_audit._tracer = self._original_tracer
        self._engine.dispose()
        self._tmp.cleanup()

    def test_extract_doc_fields_writes_one_trace_per_call(self):
        import ledger_helpers
        from llm_audit.models import LLMTrace

        # Mock OpenAI sync client.
        client = MagicMock()
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content='{"案由": "买卖合同"}'))]
        completion.usage = MagicMock(prompt_tokens=20, completion_tokens=5)
        client.chat.completions.create.return_value = completion

        result = ledger_helpers._extract_doc_fields(
            client, {"doc_type": "起诉状", "text": "诉讼请求事项..."},
        )
        self.assertEqual(result["kind"], "litigation")

        with self.SessionLocal() as db:
            row = db.execute(select(LLMTrace)).scalar_one()
            self.assertEqual(row.scene, "extract_litigation_fields")
            self.assertEqual(row.prompt_template_id, "ledger.suosostate.v1")
            self.assertEqual(row.tokens_in, 20)
            self.assertEqual(row.tokens_out, 5)


if __name__ == "__main__":
    unittest.main()
