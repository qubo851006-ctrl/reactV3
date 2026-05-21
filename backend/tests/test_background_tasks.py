import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


class BackgroundTaskEndpointTests(unittest.TestCase):
    def setUp(self):
        from auth_utils import get_current_user
        from db import Base, get_db
        from main import app
        from models import User

        self.app = app
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

        with self.SessionLocal() as db:
            db.add(User(id=1, name="admin", department="legal", role="admin", status="active"))
            db.commit()

        self.user = User(id=1, name="admin", department="legal", role="admin", status="active")
        self.app.dependency_overrides[get_current_user] = lambda: self.user

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_task_status_returns_created_task(self):
        from task_runner import create_background_task

        with self.SessionLocal() as db:
            task = create_background_task(
                db,
                task_type="ledger_merge",
                created_by=1,
                message="queued",
            )
            task_id = task.task_id

        response = self.client.get(f"/api/tasks/{task_id}")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["task_id"], task_id)
        self.assertEqual(data["type"], "ledger_merge")
        self.assertEqual(data["status"], "queued")
        self.assertEqual(data["message"], "queued")

    def test_admin_can_list_background_tasks(self):
        from task_runner import create_background_task

        with self.SessionLocal() as db:
            create_background_task(db, task_type="ledger_merge", created_by=1, message="queued")

        response = self.client.get("/api/tasks?limit=10")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(data["tasks"][0]["type"], "ledger_merge")

    def test_ledger_merge_task_endpoint_creates_queued_task(self):
        from models import BackgroundTask

        files = {
            "contract_file": (
                "contract.xlsx",
                b"PK\x03\x04minimal-xlsx-header",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        }
        with patch("routers.ledger_merge.submit_background_task") as submit:
            response = self.client.post("/api/ledger-merge/merge-task", files=files)

        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        submit.assert_called_once()

        with self.SessionLocal() as db:
            task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).one()
            self.assertEqual(task.type, "ledger_merge")
            self.assertEqual(task.status, "queued")
            self.assertEqual(task.created_by, 1)

    def test_task_runner_persists_success_result(self):
        from models import BackgroundTask
        from task_runner import _run_task, create_background_task

        with self.SessionLocal() as db:
            task = create_background_task(db, task_type="demo", created_by=1, message="queued")
            task_id = task.task_id

        def worker(ctx, _db):
            ctx.update(progress=50, message="halfway")
            return {"answer": 42}

        with patch("task_runner.SessionLocal", self.SessionLocal):
            _run_task(task_id, worker)

        with self.SessionLocal() as db:
            task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).one()
            self.assertEqual(task.status, "succeeded")
            self.assertEqual(task.progress, 100)
            self.assertIn('"answer": 42', task.result_json)

    def test_task_runner_persists_failure(self):
        from models import BackgroundTask
        from task_runner import _run_task, create_background_task

        with self.SessionLocal() as db:
            task = create_background_task(db, task_type="demo", created_by=1, message="queued")
            task_id = task.task_id

        def worker(_ctx, _db):
            raise RuntimeError("boom")

        with patch("task_runner.SessionLocal", self.SessionLocal), patch("task_runner.logger.exception"):
            _run_task(task_id, worker)

        with self.SessionLocal() as db:
            task = db.query(BackgroundTask).filter(BackgroundTask.task_id == task_id).one()
            self.assertEqual(task.status, "failed")
            self.assertEqual(task.error, "boom")


if __name__ == "__main__":
    unittest.main()
