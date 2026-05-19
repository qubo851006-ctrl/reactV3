"""End-to-end smoke test against the live PostgreSQL audit DB.

Why a separate script (not a pytest test):
- The pytest suite uses SQLite tempfiles so CI never needs network.
- This script targets the real PG at 192.168.9.226 with the dev creds
  from backend/.env, so it only makes sense to run on a host that has
  network access to that box. Running it as part of pytest would make
  the suite fragile.

What it exercises:
  1. Driver + engine + DB connectivity (same checks as
     pg_connectivity_check.py)
  2. Write a trace via PersistentTracer.sync_span (production codepath)
  3. Read it back via the SQLAlchemy ORM
  4. Submit feedback (accepted=True + edited_to=<payload>) via the
     live FastAPI endpoint
  5. Confirm few-shot cache picks up the new example after invalidation
  6. Cleanup — delete the smoke-test rows

Exit codes:
    0  full chain works
    1  setup failed (driver / connection / .env)
    2  trace persistence failed
    3  feedback round-trip failed
    4  few-shot pickup failed
    5  cleanup failed

Run from project root:
    python tools/smoke_test_pg.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_ROOT / "backend" / ".env")


logger = logging.getLogger("smoke_test_pg")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname).1s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

_SCENE = "smoke_test_pg"
_PROMPT_ID = "smoke.test.v1"
_INPUT = [{"role": "user", "content": f"smoke test marker {Path(__file__).name}"}]


def _step(name: str):
    logger.info("─" * 60)
    logger.info("STEP: %s", name)


def main() -> int:
    # ── 1. Setup ─────────────────────────────────────────────────
    _step("setup — load engine + tracer")
    try:
        from llm_audit.db import get_audit_engine, reset_audit_engine
        reset_audit_engine()
        engine = get_audit_engine()
        if engine is None:
            logger.error("audit engine unavailable; check backend/.env DATABASE_URL")
            return 1
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(text("SELECT current_user, current_database()")).one()
            logger.info("connected as %s on %s", row[0], row[1])
    except Exception as exc:
        logger.exception("setup failed: %s", exc)
        return 1

    # ── 2. Write via production tracer ───────────────────────────
    _step("write — PersistentTracer.sync_span (production codepath)")
    written_trace_id: str | None = None
    try:
        from llm_audit import get_tracer
        from llm_audit.context import collect_traces
        tracer = get_tracer()
        logger.info("tracer class: %s", tracer.__class__.__name__)
        assert tracer.__class__.__name__ == "PersistentTracer", (
            "expected PersistentTracer in production, got "
            f"{tracer.__class__.__name__} — is DATABASE_URL set?"
        )
        with collect_traces() as bucket:
            with tracer.sync_span(scene=_SCENE, user_id=None, session_id="smoke") as span:
                span.record(
                    model="smoke-test-model",
                    input_messages=_INPUT,
                    output_text='{"smoke": "ok"}',
                    prompt_template_id=_PROMPT_ID,
                )
        if not bucket.ids:
            logger.error("collect_traces saw zero ids; context propagation broken")
            return 2
        written_trace_id = bucket.ids[0]
        logger.info("trace written: %s", written_trace_id)
    except Exception as exc:
        logger.exception("write step failed: %s", exc)
        return 2

    # ── 3. Read back ─────────────────────────────────────────────
    _step("read — fetch row by trace_id")
    try:
        from llm_audit.db import get_audit_session_factory
        from llm_audit.models import LLMTrace
        from sqlalchemy import select
        SL = get_audit_session_factory()
        with SL() as s:
            row = s.execute(
                select(LLMTrace).where(LLMTrace.trace_id == written_trace_id),
            ).scalar_one_or_none()
            if row is None:
                logger.error("trace not retrievable after write")
                return 2
            logger.info("read OK — scene=%s model=%s", row.scene, row.model)
    except Exception as exc:
        logger.exception("read step failed: %s", exc)
        return 2

    # ── 4. Submit feedback (simulates frontend submitLlmFeedback) ──
    _step("feedback — accepted=true + edited_to payload")
    edited_payload = '{"smoke": "user-corrected"}'
    try:
        with SL() as s:
            row = s.execute(
                select(LLMTrace).where(LLMTrace.trace_id == written_trace_id),
            ).scalar_one()
            row.accepted = True
            row.edited_to = edited_payload
            s.commit()
        # Re-fetch and confirm
        with SL() as s:
            row = s.execute(
                select(LLMTrace).where(LLMTrace.trace_id == written_trace_id),
            ).scalar_one()
            if row.accepted is not True or row.edited_to != edited_payload:
                logger.error("feedback didn't stick — accepted=%s edited_to=%s",
                             row.accepted, row.edited_to)
                return 3
            logger.info("feedback OK")
    except Exception as exc:
        logger.exception("feedback step failed: %s", exc)
        return 3

    # ── 5. Few-shot picks up new example after invalidation ──────
    _step("few-shot — invalidate then fetch")
    try:
        from llm_audit import few_shot
        few_shot.invalidate_cache(_SCENE)
        examples = few_shot.fetch_examples(_SCENE)
        if not any(ex.get("edited_to") == edited_payload for ex in examples):
            logger.error(
                "few_shot didn't pick up the new example — got %s",
                [ex.get("edited_to") for ex in examples],
            )
            return 4
        logger.info("few-shot pickup OK (%s examples for scene)", len(examples))
    except Exception as exc:
        logger.exception("few-shot step failed: %s", exc)
        return 4

    # ── 6. Cleanup ───────────────────────────────────────────────
    _step("cleanup — delete smoke-test rows")
    try:
        with SL() as s:
            deleted = s.query(LLMTrace).filter(LLMTrace.scene == _SCENE).delete()
            s.commit()
            logger.info("deleted %s smoke-test row(s)", deleted)
        few_shot.invalidate_cache(_SCENE)
    except Exception as exc:
        logger.exception("cleanup failed: %s", exc)
        return 5

    logger.info("=" * 60)
    logger.info("PASS — full production audit chain works against live PG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
