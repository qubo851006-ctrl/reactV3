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


class OpsHealthEndpointTests(unittest.TestCase):
    def setUp(self):
        from auth_utils import get_current_user, require_admin
        from db import Base, get_db
        from main import app
        from models import BackgroundTask, User

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
            db.add(BackgroundTask(
                task_id="task_failed",
                type="ledger_merge",
                status="failed",
                progress=80,
                message="failed",
                error="boom",
                created_by=1,
            ))
            db.commit()

        self.user = User(id=1, name="admin", department="legal", role="admin", status="active")
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.app.dependency_overrides[require_admin] = lambda: self.user

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

    def test_ops_health_returns_safe_summary(self):
        env = {
            "DINGTALK_NOTIFY_ENABLED": "true",
            "DINGTALK_WEBHOOK_URL": "https://example.invalid/robot?access_token=secret",
            "DINGTALK_WEBHOOK_SECRET": "super-secret",
            "DINGTALK_ENTERPRISE_ENABLED": "true",
            "DINGTALK_APP_SECRET": "app-secret",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("routers.admin_users.engine", self.engine), \
             patch("routers.admin_users.get_audit_engine", return_value=None), \
             patch("routers.admin_users._run_git", side_effect=["master", "abc1234", "abc123456", "2026-05-21T10:00:00+08:00"]), \
             patch("routers.admin_users._recent_error_logs", return_value=[{"file": "app.err.log", "line": "ERROR failed", "modified_at": "2026-05-21T00:00:00Z"}]):
            response = self.client.get("/api/admin/ops/health")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["version"]["app_version"].startswith("v"))
        self.assertEqual(data["version"]["branch"], "master")
        self.assertEqual(data["databases"]["main"]["backend"], "sqlite")
        self.assertFalse(data["databases"]["llm_audit"]["ok"])
        self.assertTrue(data["dingtalk"]["notify_enabled"])
        self.assertTrue(data["dingtalk"]["webhook_url_configured"])
        self.assertTrue(data["dingtalk"]["webhook_secret_configured"])
        self.assertNotIn("super-secret", str(data))
        self.assertNotIn("access_token=secret", str(data))
        self.assertEqual(data["recent_failed_tasks"][0]["task_id"], "task_failed")
        self.assertEqual(data["recent_errors"][0]["line"], "ERROR failed")


if __name__ == "__main__":
    unittest.main()
