"""Tests for the enhanced operation-audit query API (#9).

GET /api/admin/audit-logs now returns user_name (joined), target_type/id,
supports an action filter and a limit, and requires admin.
"""

import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _now():
    return datetime.now(timezone.utc)


class AuditLogsQueryTests(unittest.TestCase):
    def setUp(self):
        from db import Base, get_db
        from auth_utils import get_current_user, require_admin
        from main import app
        from models import User, AuditLog

        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

        with self.SessionLocal() as db:
            db.add(User(id=1, name="张三", department="法务部", role="admin", status="active"))
            db.add(User(id=2, name="李四", department="法务部", role="user", status="active"))
            db.add(AuditLog(user_id=1, action="ledger_write", target_type="case",
                            target_id="c1", summary="写入案件台账", created_at=_now() - timedelta(minutes=5)))
            db.add(AuditLog(user_id=2, action="training_archive", target_type="training",
                            target_id="t1", summary="培训归档", created_at=_now() - timedelta(minutes=1)))
            db.add(AuditLog(user_id=None, action="login", summary="登录", created_at=_now()))
            db.commit()

        self.app = app
        self._get_db = get_db
        self._get_current_user = get_current_user
        self._require_admin = require_admin

        fake_admin = MagicMock(spec=User)
        fake_admin.id = 1
        fake_admin.name = "张三"
        fake_admin.role = "admin"
        fake_admin.status = "active"
        app.dependency_overrides[get_current_user] = lambda: fake_admin
        app.dependency_overrides[require_admin] = lambda: fake_admin

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_returns_logs_desc_with_user_name(self):
        r = self.client.get("/api/admin/audit-logs")
        self.assertEqual(r.status_code, 200)
        logs = r.json()["logs"]
        self.assertEqual(len(logs), 3)
        # newest first: login (no user) is most recent
        self.assertEqual(logs[0]["action"], "login")
        self.assertIsNone(logs[0]["user_name"])
        # user_name joined for the rest
        by_action = {l["action"]: l for l in logs}
        self.assertEqual(by_action["ledger_write"]["user_name"], "张三")
        self.assertEqual(by_action["training_archive"]["user_name"], "李四")
        # target fields surfaced
        self.assertEqual(by_action["ledger_write"]["target_type"], "case")
        self.assertEqual(by_action["ledger_write"]["target_id"], "c1")

    def test_action_filter(self):
        r = self.client.get("/api/admin/audit-logs?action=ledger")
        logs = r.json()["logs"]
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["action"], "ledger_write")

    def test_limit_caps_results(self):
        r = self.client.get("/api/admin/audit-logs?limit=1")
        self.assertEqual(len(r.json()["logs"]), 1)

    def test_non_admin_forbidden(self):
        from fastapi import HTTPException

        def deny():
            raise HTTPException(status_code=403, detail="需要管理员权限")

        self.app.dependency_overrides[self._require_admin] = deny
        r = self.client.get("/api/admin/audit-logs")
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
