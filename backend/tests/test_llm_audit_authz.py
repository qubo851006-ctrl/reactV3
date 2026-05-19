"""Authorization tests for /api/llm-traces endpoints.

What this file gates
- Only admins can read /list / scenes / scene-stats / trace-detail (so a
  regular user can't trivially exfiltrate other users' extraction prompts
  or LLM output, which often contain document text).
- Regular users CAN submit feedback (the workflow needs them to confirm
  their own extractions), but ONLY on traces THEY created — never on
  someone else's trace.
- Admins bypass the ownership check.

Why this matters
- The feedback endpoint is the only non-admin write path into the audit
  DB. If the ownership check breaks, user A could mark user B's
  extraction as "accepted" and pollute the few-shot pool with output
  user A never reviewed. Worst case, an attacker grinds through random
  trace_ids and influences the prompt steering of unrelated users'
  flows.
"""
from __future__ import annotations

import secrets
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _isolated_factory(tmp_db: Path):
    from llm_audit.db import AuditBase
    import llm_audit.models  # noqa: F401
    engine = create_engine(
        f"sqlite:///{tmp_db}",
        connect_args={"check_same_thread": False},
    )
    AuditBase.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _fake_user(uid: int, role: str = "user"):
    from models import User
    u = MagicMock(spec=User)
    u.id = uid
    u.name = f"u{uid}"
    u.role = role
    u.status = "active"
    u.department = "测试"
    u.last_login_at = None
    return u


def _client_for(user):
    """TestClient with auth deps overridden to return `user`."""
    from main import app
    from auth_utils import get_current_user, require_admin

    app.dependency_overrides[get_current_user] = lambda: user
    if user.role == "admin":
        app.dependency_overrides[require_admin] = lambda: user
    else:
        from fastapi import HTTPException

        def _block():
            raise HTTPException(status_code=403, detail="需要管理员权限")
        app.dependency_overrides[require_admin] = _block
    return TestClient(app), app


class _AuditEnvMixin:
    """Per-test SQLite-backed audit DB + clean tracer/cache."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_db = Path(self._tmp.name) / "audit.db"
        self._engine, self.SessionLocal = _isolated_factory(tmp_db)

        from llm_audit.db import set_audit_engine, reset_audit_engine
        from llm_audit.tracer import PersistentTracer
        from llm_audit import few_shot
        import llm_audit

        self._reset_audit_engine = reset_audit_engine
        set_audit_engine(self._engine, self.SessionLocal)
        self._orig_tracer = llm_audit._tracer
        llm_audit.set_tracer(PersistentTracer(session_factory=self.SessionLocal))
        few_shot.invalidate_cache()

    def tearDown(self):
        import llm_audit
        from llm_audit import few_shot
        # Cleanup must be defensive — different tests register different
        # app.dependency_overrides; do a blanket clear.
        from main import app
        app.dependency_overrides.clear()
        llm_audit._tracer = self._orig_tracer
        few_shot.invalidate_cache()
        self._reset_audit_engine()
        self._engine.dispose()
        self._tmp.cleanup()

    def _seed_trace_for(self, owner_id: int | None) -> str:
        """Insert a trace owned by `owner_id` (or unowned if None). Returns
        the trace_id so a test can target it by URL."""
        from llm_audit.models import LLMTrace
        trace_id = secrets.token_hex(12)
        with self.SessionLocal() as s:
            s.add(LLMTrace(
                trace_id=trace_id,
                scene="some_scene",
                model="m", prompt_template_id="m.v1",
                input_hash="h" * 64,
                input_preview="x",
                input_text='[{"role":"user","content":"x"}]',
                output_text="y",
                tokens_in=0, tokens_out=0, duration_ms=0,
                user_id=owner_id, session_id="s",
                created_at=datetime.now(timezone.utc),
            ))
            s.commit()
        return trace_id


class AdminReadAccessTests(_AuditEnvMixin, unittest.TestCase):
    """Read endpoints require admin."""

    def test_list_traces_403_for_regular_user(self):
        user = _fake_user(uid=1, role="user")
        client, _ = _client_for(user)
        r = client.get("/api/llm-traces")
        self.assertEqual(r.status_code, 403)

    def test_list_traces_200_for_admin(self):
        admin = _fake_user(uid=99, role="admin")
        client, _ = _client_for(admin)
        r = client.get("/api/llm-traces")
        self.assertEqual(r.status_code, 200)

    def test_scenes_stats_403_for_regular_user(self):
        user = _fake_user(uid=1, role="user")
        client, _ = _client_for(user)
        r = client.get("/api/llm-traces/scenes/stats")
        self.assertEqual(r.status_code, 403)

    def test_trace_detail_403_for_regular_user(self):
        admin_seed = _fake_user(uid=99, role="admin")
        _, _ = _client_for(admin_seed)
        tid = self._seed_trace_for(owner_id=99)

        user = _fake_user(uid=1, role="user")
        client, _ = _client_for(user)
        r = client.get(f"/api/llm-traces/{tid}")
        self.assertEqual(r.status_code, 403)


class FeedbackOwnershipTests(_AuditEnvMixin, unittest.TestCase):
    """The only non-admin write endpoint — ownership is enforced."""

    def test_user_can_submit_feedback_for_own_trace(self):
        owner_id = 7
        tid = self._seed_trace_for(owner_id=owner_id)

        client, _ = _client_for(_fake_user(uid=owner_id, role="user"))
        r = client.post(
            f"/api/llm-traces/{tid}/feedback",
            json={"accepted": True, "edited_to": None},
        )
        self.assertEqual(r.status_code, 200)

    def test_user_cannot_submit_feedback_for_other_users_trace(self):
        # User 7 owns the trace
        tid = self._seed_trace_for(owner_id=7)

        # User 99 tries to send feedback on it
        client, _ = _client_for(_fake_user(uid=99, role="user"))
        r = client.post(
            f"/api/llm-traces/{tid}/feedback",
            json={"accepted": True, "edited_to": '{"attack": "data"}'},
        )
        self.assertEqual(r.status_code, 403)

        # And the row in PG remains unchanged
        from sqlalchemy import select
        from llm_audit.models import LLMTrace
        with self.SessionLocal() as s:
            row = s.execute(
                select(LLMTrace).where(LLMTrace.trace_id == tid),
            ).scalar_one()
            self.assertIsNone(row.accepted)
            self.assertIsNone(row.edited_to)

    def test_admin_can_submit_feedback_for_any_trace(self):
        # User 7 owns the trace
        tid = self._seed_trace_for(owner_id=7)

        # Admin overrides
        admin = _fake_user(uid=999, role="admin")
        client, _ = _client_for(admin)
        r = client.post(
            f"/api/llm-traces/{tid}/feedback",
            json={"accepted": True, "edited_to": '{"admin": "override"}'},
        )
        self.assertEqual(r.status_code, 200)

    def test_user_can_submit_feedback_for_unowned_trace(self):
        """Traces where user_id IS NULL (e.g. background jobs) accept
        feedback from any logged-in user — the ownership check only
        bites when there IS a specific owner."""
        tid = self._seed_trace_for(owner_id=None)
        client, _ = _client_for(_fake_user(uid=42, role="user"))
        r = client.post(
            f"/api/llm-traces/{tid}/feedback",
            json={"accepted": True, "edited_to": None},
        )
        self.assertEqual(r.status_code, 200)

    def test_feedback_on_missing_trace_returns_404(self):
        client, _ = _client_for(_fake_user(uid=7, role="user"))
        r = client.post(
            "/api/llm-traces/never-existed/feedback",
            json={"accepted": True, "edited_to": None},
        )
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
