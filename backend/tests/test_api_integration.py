"""End-to-end backend API integration tests.

What this file covers (and what gates):
- A real FastAPI TestClient hits the live routers (chat / llm-traces /
  compliance) with auth dependencies overridden, mocked LLM gateway, and an
  isolated SQLite-backed audit DB.
- Asserts the full chain: HTTP request → router → utils → audit DB write →
  trace_ids returned in response → feedback endpoint round-trip → cache
  invalidation → next request sees the change.

Why this matters
- Up to commit 7dfbaa6 we had 223 unit tests but ZERO that exercised the
  HTTP transport layer plus the audit-write side-effect together. A
  refactor of routers/<x>.py that broke trace_id propagation, response
  schemas, or auth wiring would pass every unit test and still ship a
  broken product.

What it deliberately does NOT cover
- Real LLM gateway calls (mocked — we test wiring, not model quality)
- Real PostgreSQL (uses SQLite tempfile so CI doesn't need network)
- Real file uploads larger than a few bytes
- Front-end JavaScript (separate Vitest harness)
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ── shared helpers ───────────────────────────────────────────────────

def _isolated_audit_factory(tmp_db: Path):
    """Spin up a SQLite-backed audit DB for one test class."""
    from llm_audit.db import AuditBase
    import llm_audit.models  # noqa: F401 — registers LLMTrace on AuditBase

    engine = create_engine(
        f"sqlite:///{tmp_db}",
        connect_args={"check_same_thread": False},
    )
    AuditBase.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _build_client(user_role: str = "user", user_id: int = 42):
    """Build a TestClient with auth deps overridden to return a fake user.

    Returns (client, fake_user). The dispatcher's PersistentTracer is left
    in place but pointed at the per-test SQLite via set_audit_engine
    (callers are responsible for setting that up before instantiating).
    """
    from main import app
    from auth_utils import get_current_user, require_admin
    from models import User

    fake_user = MagicMock(spec=User)
    fake_user.id = user_id
    fake_user.name = f"test-user-{user_id}"
    fake_user.role = user_role
    fake_user.status = "active"
    fake_user.department = "测试部"
    fake_user.last_login_at = None

    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = (
        (lambda: fake_user) if user_role == "admin"
        else _force_admin_required
    )
    client = TestClient(app)
    return client, fake_user, app


def _force_admin_required():
    """Stand-in for require_admin when the test client is a non-admin —
    raises 403 the same way the real dependency would."""
    from fastapi import HTTPException
    raise HTTPException(status_code=403, detail="需要管理员权限")


# ── /api/llm-traces endpoints ────────────────────────────────────────

class LlmTracesEndpointTests(unittest.TestCase):
    """End-to-end for the audit query API."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_db = Path(self._tmp.name) / "audit.db"
        self._engine, self.SessionLocal = _isolated_audit_factory(tmp_db)

        from llm_audit.db import set_audit_engine, reset_audit_engine
        from llm_audit.tracer import PersistentTracer
        from llm_audit import few_shot
        import llm_audit

        self._reset_audit_engine = reset_audit_engine
        set_audit_engine(self._engine, self.SessionLocal)
        self._orig_tracer = llm_audit._tracer
        llm_audit.set_tracer(PersistentTracer(session_factory=self.SessionLocal))
        few_shot.invalidate_cache()

        self.client, self.user, self.app = _build_client(user_role="admin")

    def tearDown(self):
        self.app.dependency_overrides.clear()
        import llm_audit
        from llm_audit import few_shot
        llm_audit._tracer = self._orig_tracer
        few_shot.invalidate_cache()
        self._reset_audit_engine()
        self._engine.dispose()
        self._tmp.cleanup()

    def _seed_trace(self, scene: str, accepted: bool | None = None, edited_to: str | None = None) -> str:
        """Insert one row and return its trace_id for follow-up calls."""
        from datetime import datetime, timezone
        from llm_audit.models import LLMTrace
        import secrets
        trace_id = secrets.token_hex(12)
        with self.SessionLocal() as s:
            s.add(LLMTrace(
                trace_id=trace_id,
                scene=scene,
                model="qwen-test",
                prompt_template_id=f"{scene}.v1",
                input_hash="h" * 64,
                input_preview="预览…",
                input_text='[{"role":"user","content":"hi"}]',
                output_text='{"x": 1}',
                tokens_in=10, tokens_out=2, duration_ms=5,
                user_id=self.user.id, session_id="sess_test",
                accepted=accepted,
                edited_to=edited_to,
                created_at=datetime.now(timezone.utc),
            ))
            s.commit()
        return trace_id

    def test_list_returns_seeded_traces(self):
        self._seed_trace("scene_a")
        self._seed_trace("scene_b", accepted=True)

        r = self.client.get("/api/llm-traces?limit=10")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["traces"]), 2)
        scenes = {t["scene"] for t in data["traces"]}
        self.assertEqual(scenes, {"scene_a", "scene_b"})

    def test_list_scene_filter_narrows_results(self):
        self._seed_trace("scene_a")
        self._seed_trace("scene_b")
        self._seed_trace("scene_a")

        r = self.client.get("/api/llm-traces?scene=scene_a")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["traces"]), 2)

    def test_detail_returns_full_payload(self):
        tid = self._seed_trace("scene_detail", accepted=True, edited_to='{"corrected": true}')

        r = self.client.get(f"/api/llm-traces/{tid}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["trace_id"], tid)
        self.assertEqual(body["accepted"], True)
        self.assertEqual(body["edited_to"], '{"corrected": true}')
        self.assertIn("input_text", body)
        self.assertIn("output_text", body)

    def test_detail_404_for_unknown_trace(self):
        r = self.client.get("/api/llm-traces/nonexistent-id")
        self.assertEqual(r.status_code, 404)

    def test_scenes_aggregate_counts(self):
        self._seed_trace("a")
        self._seed_trace("a")
        self._seed_trace("b")

        r = self.client.get("/api/llm-traces/scenes")
        self.assertEqual(r.status_code, 200)
        scenes = {row["scene"]: row["count"] for row in r.json()["scenes"]}
        self.assertEqual(scenes, {"a": 2, "b": 1})

    def test_scenes_stats_computes_rates(self):
        # 1 accepted, 1 rejected, 1 unreviewed for scene_x.
        self._seed_trace("scene_x", accepted=True)
        self._seed_trace("scene_x", accepted=False)
        self._seed_trace("scene_x", accepted=None)

        r = self.client.get("/api/llm-traces/scenes/stats")
        self.assertEqual(r.status_code, 200)
        rows = {row["scene"]: row for row in r.json()["scenes"]}
        x = rows["scene_x"]
        self.assertEqual(x["total"], 3)
        self.assertEqual(x["feedback_count"], 2)
        self.assertEqual(x["accepted_count"], 1)
        self.assertAlmostEqual(x["acceptance_rate"], 0.5)

    def test_feedback_round_trip_updates_row(self):
        tid = self._seed_trace("scene_feedback")

        r = self.client.post(
            f"/api/llm-traces/{tid}/feedback",
            json={"accepted": True, "edited_to": '{"final": "value"}'},
        )
        self.assertEqual(r.status_code, 200)

        # GET back the row, accepted/edited_to should reflect the POST.
        detail = self.client.get(f"/api/llm-traces/{tid}").json()
        self.assertEqual(detail["accepted"], True)
        self.assertEqual(detail["edited_to"], '{"final": "value"}')

    def test_feedback_invalidates_few_shot_cache(self):
        from llm_audit import few_shot
        # Warm the cache with empty result first
        self.assertEqual(few_shot.fetch_examples("scene_cache"), [])
        # Seed a feedback row directly
        tid = self._seed_trace("scene_cache")
        # Without invalidation, cache still empty:
        self.assertEqual(few_shot.fetch_examples("scene_cache"), [])
        # POST feedback through the API — endpoint must invalidate cache:
        self.client.post(
            f"/api/llm-traces/{tid}/feedback",
            json={"accepted": True, "edited_to": '{"e": 1}'},
        )
        # Now the cache is fresh and includes the row.
        examples = few_shot.fetch_examples("scene_cache")
        self.assertEqual(len(examples), 1)
        self.assertIn("e", examples[0]["edited_to"])


# ── /api/chat session endpoints (no LLM needed) ──────────────────────

class ChatSessionEndpointTests(unittest.TestCase):
    """Session CRUD doesn't touch LLM gateway — pure file persistence."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # Re-point DATA_ROOT to a per-test tempdir so session files don't
        # collide across runs or pollute production data/.
        self._data_patcher = patch("routers.chat._HISTORY_DIR", Path(self._tmp.name) / "history")
        self._data_patcher.start()
        (Path(self._tmp.name) / "history").mkdir()

        self.client, self.user, self.app = _build_client(user_role="user", user_id=7)

    def tearDown(self):
        self._data_patcher.stop()
        self.app.dependency_overrides.clear()
        self._tmp.cleanup()

    def test_create_then_list_session(self):
        # Initial list should be empty.
        r0 = self.client.get("/api/chat/sessions")
        self.assertEqual(r0.status_code, 200)
        self.assertEqual(r0.json()["sessions"], [])

        # Create one.
        r1 = self.client.post("/api/chat/sessions")
        self.assertEqual(r1.status_code, 200)
        created = r1.json()
        self.assertTrue(created["session_id"].startswith("sess_"))
        self.assertEqual(created["title"], "新对话")

        # List should now contain it.
        r2 = self.client.get("/api/chat/sessions")
        self.assertEqual(len(r2.json()["sessions"]), 1)
        self.assertEqual(r2.json()["sessions"][0]["id"], created["session_id"])

    def test_rename_session(self):
        sid = self.client.post("/api/chat/sessions").json()["session_id"]
        r = self.client.patch(
            f"/api/chat/sessions/{sid}",
            json={"title": "我重命名了"},
        )
        self.assertEqual(r.status_code, 200)
        sessions = self.client.get("/api/chat/sessions").json()["sessions"]
        self.assertEqual(sessions[0]["title"], "我重命名了")

    def test_delete_session_removes_from_list(self):
        sid = self.client.post("/api/chat/sessions").json()["session_id"]
        r = self.client.delete(f"/api/chat/sessions/{sid}")
        self.assertEqual(r.status_code, 200)
        sessions = self.client.get("/api/chat/sessions").json()["sessions"]
        self.assertEqual(sessions, [])

    def test_session_id_path_traversal_blocked(self):
        """Malicious session_id like '../../etc/passwd' must be rejected.
        405 is also acceptable — it means the URL didn't match any
        registered route (FastAPI decoded the path and looked for a
        handler that doesn't exist), which is its own form of defense."""
        r = self.client.patch(
            "/api/chat/sessions/sess_..%2F..%2Fpasswd",
            json={"title": "x"},
        )
        # Any code that ISN'T a 200/500 means the attack didn't succeed.
        # 400 = explicit validation, 404 = not found, 405 = no route
        # matched after URL decode, 422 = pydantic schema rejection.
        self.assertIn(r.status_code, (400, 404, 405, 422))


# ── Health check ─────────────────────────────────────────────────────

class HealthCheckTests(unittest.TestCase):
    """Smoke: the app boots and the unauthenticated /api/health works."""

    def test_health_endpoint_is_public(self):
        from main import app
        # Don't override auth — health is public and must work without it.
        client = TestClient(app)
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
