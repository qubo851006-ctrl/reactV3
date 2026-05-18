"""Verify the PostgreSQL audit DB is reachable and the llm_traces table exists.

Run from project root:
    python tools/pg_connectivity_check.py

Exit codes:
    0  all good
    1  connection failed
    2  connected but llm_traces missing (run init_audit_db first)
    3  table exists but a sample insert/select round-trip failed
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make `backend/` importable without changing CWD.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / "backend" / ".env")


def main() -> int:
    print("=" * 60)
    print("PostgreSQL audit DB connectivity check")
    print("=" * 60)

    url_env = os.getenv("LLM_AUDIT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url_env:
        print("[FAIL] Neither LLM_AUDIT_DATABASE_URL nor DATABASE_URL is set.")
        return 1
    print(f"URL (raw):  {_redact(url_env)}")

    # ── 1. Driver import
    try:
        import psycopg  # noqa: F401
        print(f"Driver:     psycopg v{psycopg.__version__}")
    except ImportError as e:
        print(f"[FAIL] psycopg not installed: {e}")
        print("       Run: pip install 'psycopg[binary]==3.2.3'")
        return 1

    # ── 2. Engine build + connect
    from llm_audit.db import get_audit_engine
    engine = get_audit_engine()
    if engine is None:
        print("[FAIL] get_audit_engine() returned None — URL parsing issue?")
        return 1

    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT current_user, current_database(), version()",
            )).one()
            print(f"User:       {row[0]}")
            print(f"Database:   {row[1]}")
            print(f"Server:     {row[2][:80]}")
    except Exception as e:
        print(f"[FAIL] Connection failed: {type(e).__name__}: {e}")
        return 1

    # ── 3. Table presence
    from sqlalchemy import inspect
    inspector = inspect(engine)
    if "llm_traces" not in inspector.get_table_names():
        print("[WARN] llm_traces table missing.")
        print("       Run: python -c 'from llm_audit.db import init_audit_db; init_audit_db()'")
        return 2
    cols = [c["name"] for c in inspector.get_columns("llm_traces")]
    print(f"Columns:    {len(cols)} ({', '.join(cols[:6])}…)")

    # ── 4. Round-trip insert/select/delete
    from datetime import datetime, timezone
    from llm_audit.db import get_audit_session_factory
    from llm_audit.models import LLMTrace

    SessionLocal = get_audit_session_factory()
    if SessionLocal is None:
        print("[FAIL] session factory unavailable after engine init")
        return 1
    probe_trace_id = "connectivity_probe"
    try:
        with SessionLocal() as s:
            s.query(LLMTrace).filter(LLMTrace.trace_id == probe_trace_id).delete()
            s.add(LLMTrace(
                trace_id=probe_trace_id,
                scene="connectivity_check",
                input_hash="",
                tokens_in=0, tokens_out=0, duration_ms=0,
                created_at=datetime.now(timezone.utc),
            ))
            s.commit()
            row = s.query(LLMTrace).filter(LLMTrace.trace_id == probe_trace_id).one()
            assert row.scene == "connectivity_check"
            s.delete(row)
            s.commit()
        print("Round-trip: OK (insert + select + delete)")
    except Exception as e:
        print(f"[FAIL] Round-trip failed: {type(e).__name__}: {e}")
        return 3

    print("=" * 60)
    print("[PASS] llm_audit DB is ready.")
    return 0


def _redact(url: str) -> str:
    # postgresql://user:password@host/db → postgresql://user:***@host/db
    import re
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***\2", url)


if __name__ == "__main__":
    raise SystemExit(main())
