"""Archive old llm_traces rows so the hot table stays fast.

What it does
-------------
Rows in llm_traces older than ARCHIVE_DAYS days are moved to
llm_traces_archive (same schema) and deleted from the hot table. The
archive table is created on first run.

Why
---
llm_traces grows ~one row per LLM call. After ~6 months of real usage
the table is large enough that the dashboard's group-by-scene scan
slows down. Archival keeps the dashboard snappy without losing
history — the archive table is queryable, just not indexed for fast
filtering.

Operations
----------
- ARCHIVE_DAYS defaults to 90; override with --days N
- --dry-run prints counts without modifying anything
- Idempotent: re-running just moves any new rows that crossed the
  cutoff since last run

Wire to Task Scheduler weekly:
    schtasks /create /tn "reactV3 LLM trace archive" \
        /tr "python D:\\claude\\reactV3\\tools\\archive_llm_traces.py" \
        /sc weekly /d SUN /st 03:00
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make backend/ importable + load .env
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_ROOT / "backend" / ".env")

from sqlalchemy import text  # noqa: E402

from llm_audit.db import AuditBase, get_audit_engine, reset_audit_engine  # noqa: E402


logger = logging.getLogger("archive_llm_traces")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname).1s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


# Use a dedicated archive table that mirrors the live schema. Generated on
# first run via CREATE TABLE LIKE so future column additions stay in sync.
_CREATE_ARCHIVE_SQL = """
CREATE TABLE IF NOT EXISTS llm_traces_archive
    (LIKE llm_traces INCLUDING DEFAULTS INCLUDING INDEXES)
"""

_COPY_OLD_SQL = """
INSERT INTO llm_traces_archive
SELECT * FROM llm_traces
WHERE created_at < :cutoff
ON CONFLICT (trace_id) DO NOTHING
"""

_DELETE_OLD_SQL = """
DELETE FROM llm_traces WHERE created_at < :cutoff
"""

_COUNT_TARGET_SQL = """
SELECT count(*) FROM llm_traces WHERE created_at < :cutoff
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive llm_traces rows older than N days.")
    parser.add_argument("--days", type=int, default=90, help="Cutoff in days (default 90).")
    parser.add_argument("--dry-run", action="store_true", help="Count only — no writes.")
    args = parser.parse_args()

    reset_audit_engine()  # ensure we picked up the latest .env on each run
    engine = get_audit_engine()
    if engine is None:
        logger.error("audit DB not reachable — abort")
        return 1

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    logger.info("cutoff: rows created before %s will be archived", cutoff.isoformat())

    with engine.begin() as conn:
        # Make sure the archive table exists (mirrors live schema).
        conn.execute(text(_CREATE_ARCHIVE_SQL))

        n = conn.execute(text(_COUNT_TARGET_SQL), {"cutoff": cutoff}).scalar() or 0
        logger.info("rows to archive: %s", n)
        if n == 0:
            logger.info("nothing to do")
            return 0

        if args.dry_run:
            logger.info("dry-run — leaving rows in place")
            return 0

        moved = conn.execute(text(_COPY_OLD_SQL), {"cutoff": cutoff}).rowcount
        deleted = conn.execute(text(_DELETE_OLD_SQL), {"cutoff": cutoff}).rowcount
        logger.info("moved %s, deleted %s", moved, deleted)

        # Sanity: deleted should equal moved (or less if a previous run
        # already copied but didn't delete). If deleted > moved, we lost
        # data — should be impossible because of the same cutoff in one
        # transaction, but log it just in case.
        if deleted > moved:
            logger.warning("data loss check: deleted (%s) > moved (%s)", deleted, moved)
            return 2

    # Touch the schema-of-record: make sure live table is registered in
    # AuditBase metadata (no-op when models are already imported).
    import llm_audit.models  # noqa: F401
    _ = AuditBase  # silence linter; we only need the module-load side effect

    logger.info("archive complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
