"""Tests for orphaned background-task reclamation on startup (P1 #3).

When the process restarts, the in-process ThreadPoolExecutor dies and any
task left in queued/running has no worker behind it — its DB row would
otherwise stay stuck forever, spinning in the UI. reclaim_orphaned_tasks()
gives every such orphan a terminal 'failed' state.

Cases:
  1. queued + running orphans both become failed with an explanatory error
  2. terminal tasks (succeeded/failed/cancelled) are left untouched
  3. empty DB / no orphans returns 0
  4. reclaim is idempotent (second run finds nothing)
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _now():
    return datetime.now(timezone.utc)


class ReclaimOrphanedTasksTests(unittest.TestCase):
    def setUp(self):
        from db import Base
        from models import BackgroundTask

        self.BackgroundTask = BackgroundTask
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _add(self, db, task_id, status):
        db.add(self.BackgroundTask(
            task_id=task_id, type="ledger_merge", status=status,
            progress=50 if status == "running" else 0,
            message="x", created_by=1, created_at=_now(), updated_at=_now(),
        ))

    def _reclaim(self):
        import task_runner
        with self.SessionLocal() as db:
            return task_runner.reclaim_orphaned_tasks(db)

    # Case 1 + 2 combined: orphans flip, terminal untouched
    def test_orphans_failed_terminal_untouched(self):
        with self.SessionLocal() as db:
            self._add(db, "q1", "queued")
            self._add(db, "r1", "running")
            self._add(db, "s1", "succeeded")
            self._add(db, "f1", "failed")
            self._add(db, "c1", "cancelled")
            db.commit()

        count = self._reclaim()
        self.assertEqual(count, 2, "only queued + running are orphans")

        with self.SessionLocal() as db:
            by_id = {t.task_id: t for t in db.query(self.BackgroundTask).all()}
            # orphans flipped
            for tid in ("q1", "r1"):
                self.assertEqual(by_id[tid].status, "failed")
                self.assertIn("重启", by_id[tid].error)
                self.assertIsNotNone(by_id[tid].finished_at)
            # terminal untouched
            self.assertEqual(by_id["s1"].status, "succeeded")
            self.assertEqual(by_id["f1"].status, "failed")
            self.assertEqual(by_id["f1"].error, None)  # not overwritten
            self.assertEqual(by_id["c1"].status, "cancelled")

    # Case 3: no orphans
    def test_no_orphans_returns_zero(self):
        with self.SessionLocal() as db:
            self._add(db, "s1", "succeeded")
            db.commit()
        self.assertEqual(self._reclaim(), 0)

    # Case 4: idempotent
    def test_idempotent(self):
        with self.SessionLocal() as db:
            self._add(db, "r1", "running")
            db.commit()
        self.assertEqual(self._reclaim(), 1)
        self.assertEqual(self._reclaim(), 0, "second run finds nothing")


if __name__ == "__main__":
    unittest.main()
