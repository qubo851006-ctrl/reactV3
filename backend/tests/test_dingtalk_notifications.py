import base64
import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


class DingtalkNotificationTests(unittest.TestCase):
    def test_disabled_without_configuration(self):
        from integrations.dingtalk.notifications import send_dingtalk_notification

        with patch.dict("os.environ", {}, clear=True), \
             patch("httpx.post") as post:
            sent = send_dingtalk_notification(
                title="合规审查完成",
                summary="测试事项",
                level="success",
            )

        self.assertFalse(sent)
        post.assert_not_called()

    def test_signed_webhook_url_uses_dingtalk_secret_format(self):
        from integrations.dingtalk.notifications import _signed_webhook_url

        signed = _signed_webhook_url(
            "https://oapi.dingtalk.com/robot/send?access_token=abc",
            "secret",
            timestamp=1234567890,
        )

        parsed = urlparse(signed)
        qs = parse_qs(parsed.query)
        expected = base64.b64encode(
            hmac.new(
                b"secret",
                b"1234567890\nsecret",
                digestmod=hashlib.sha256,
            ).digest()
        ).decode()
        self.assertEqual(qs["timestamp"], ["1234567890"])
        self.assertEqual(qs["sign"], [expected])
        self.assertEqual(qs["access_token"], ["abc"])

    def test_http_failure_is_swallowed(self):
        from integrations.dingtalk.notifications import send_dingtalk_notification

        env = {
            "DINGTALK_NOTIFY_ENABLED": "true",
            "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=abc",
            "DINGTALK_WEBHOOK_SECRET": "secret",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("httpx.post", side_effect=httpx.TimeoutException("slow")), \
             patch("integrations.dingtalk.notifications.logger") as logger:
            sent = send_dingtalk_notification(
                title="三台账合并失败",
                summary="网络超时",
                level="error",
            )

        self.assertFalse(sent)
        logger.exception.assert_called_once_with("dingtalk notify failed")

    def test_configured_notification_posts_markdown_without_sensitive_body(self):
        from integrations.dingtalk.notifications import send_dingtalk_notification

        env = {
            "DINGTALK_NOTIFY_ENABLED": "true",
            "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=abc",
            "DINGTALK_WEBHOOK_SECRET": "",
            "DINGTALK_NOTIFY_BASE_URL": "https://v3.example.test",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("httpx.post") as post:
            post.return_value = httpx.Response(200, json={"errcode": 0})

            sent = send_dingtalk_notification(
                title="授权请示生成完成",
                summary="关于测试项目相关工作授权",
                level="success",
                user_name="张三",
                session_id="sess_abc",
            )

        self.assertTrue(sent)
        payload = json.loads(post.call_args.kwargs["content"].decode("utf-8"))
        markdown_text = payload["markdown"]["text"]
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertIn("授权请示生成完成", markdown_text)
        self.assertIn("张三", markdown_text)
        self.assertIn("https://v3.example.test/?session_id=sess_abc", markdown_text)
        self.assertNotIn("PDF", markdown_text)

    def test_configured_notification_can_at_dingtalk_user_id(self):
        from integrations.dingtalk.notifications import send_dingtalk_notification

        env = {
            "DINGTALK_NOTIFY_ENABLED": "true",
            "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=abc",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("httpx.post") as post:
            post.return_value = httpx.Response(200, json={"errcode": 0})

            sent = send_dingtalk_notification(
                title="案件台账信息识别完成",
                summary="测试案件",
                level="success",
                user_name="张三",
                at_user_id="ding-user-1",
            )

        self.assertTrue(sent)
        payload = json.loads(post.call_args.kwargs["content"].decode("utf-8"))
        self.assertEqual(payload["at"], {"atUserIds": ["ding-user-1"], "isAtAll": False})
        self.assertIn("@ding-user-1", payload["markdown"]["text"])
        self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "application/json; charset=utf-8")

    def test_notify_handles_user_without_dingtalk_binding(self):
        """Regression: a user whose dingtalk_user_id is NULL must not crash the
        best-effort notification path. Previously `at_user_id.strip()` raised
        AttributeError on None and bubbled up, failing the whole business task
        (training/compliance extract etc.) for every user not bound to DingTalk."""
        from integrations.dingtalk.notifications import notify_task_failure, notify_task_success

        class _UserNoBinding:
            id = 3
            name = "李四"
            dingtalk_user_id = None  # not bound to DingTalk

        env = {
            "DINGTALK_NOTIFY_ENABLED": "true",
            "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=abc",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("integrations.dingtalk.notifications._record_notification_log"), \
             patch("httpx.post") as post:
            post.return_value = httpx.Response(200, json={"errcode": 0})
            # Must not raise despite dingtalk_user_id being None.
            ok_success = notify_task_success(task="培训信息识别", summary="主题", user=_UserNoBinding())
            ok_failure = notify_task_failure(task="培训信息识别", summary="出错", user=_UserNoBinding())

        self.assertTrue(ok_success)
        self.assertTrue(ok_failure)


class DingtalkNotificationLogTests(unittest.TestCase):
    def setUp(self):
        from db import Base
        import models  # noqa: F401

        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_success_notification_records_log(self):
        from integrations.dingtalk.notifications import send_dingtalk_notification
        from models import NotificationLog

        env = {
            "DINGTALK_NOTIFY_ENABLED": "true",
            "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=abc",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("db.SessionLocal", self.SessionLocal), \
             patch("httpx.post") as post:
            post.return_value = httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

            sent = send_dingtalk_notification(
                title="培训信息识别完成",
                summary="培训主题",
                level="success",
                task="培训信息识别",
                stage="AI 识别",
                user_id=7,
                user_name="张三",
            )

        self.assertTrue(sent)
        with self.SessionLocal() as db:
            log = db.query(NotificationLog).one()
            self.assertEqual(log.task, "培训信息识别")
            self.assertEqual(log.level, "success")
            self.assertEqual(log.stage, "AI 识别")
            self.assertEqual(log.user_id, 7)
            self.assertTrue(log.sent)
            self.assertEqual(log.provider_code, "0")

    def test_success_switch_can_skip_without_http_call(self):
        from integrations.dingtalk.notifications import send_dingtalk_notification
        from models import NotificationLog

        env = {
            "DINGTALK_NOTIFY_ENABLED": "true",
            "DINGTALK_NOTIFY_ON_SUCCESS": "false",
            "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=abc",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("db.SessionLocal", self.SessionLocal), \
             patch("httpx.post") as post:
            sent = send_dingtalk_notification(
                title="三台账合并完成",
                summary="合同条数：1",
                level="success",
                task="三台账合并",
            )

        self.assertFalse(sent)
        post.assert_not_called()
        with self.SessionLocal() as db:
            log = db.query(NotificationLog).one()
            self.assertFalse(log.sent)
            self.assertEqual(log.skipped_reason, "success_disabled")

    def test_mention_switch_removes_at_payload(self):
        from integrations.dingtalk.notifications import send_dingtalk_notification

        env = {
            "DINGTALK_NOTIFY_ENABLED": "true",
            "DINGTALK_NOTIFY_MENTION_USER": "false",
            "DINGTALK_WEBHOOK_URL": "https://oapi.dingtalk.com/robot/send?access_token=abc",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("db.SessionLocal", self.SessionLocal), \
             patch("httpx.post") as post:
            post.return_value = httpx.Response(200, json={"errcode": 0})

            sent = send_dingtalk_notification(
                title="案件台账信息识别完成",
                summary="测试案件",
                level="success",
                at_user_id="ding-user-1",
            )

        self.assertTrue(sent)
        payload = json.loads(post.call_args.kwargs["content"].decode("utf-8"))
        self.assertNotIn("at", payload)
        self.assertNotIn("@ding-user-1", payload["markdown"]["text"])

    def test_work_notice_channel_can_succeed_without_webhook(self):
        from integrations.dingtalk.notifications import send_dingtalk_notification
        from models import NotificationLog

        env = {
            "DINGTALK_NOTIFY_ENABLED": "true",
            "DINGTALK_ENTERPRISE_ENABLED": "true",
            "DINGTALK_WORK_NOTICE_ENABLED": "true",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("db.SessionLocal", self.SessionLocal), \
             patch("integrations.dingtalk.notifications.send_work_notice", return_value={"errcode": 0, "errmsg": "ok"}):
            sent = send_dingtalk_notification(
                title="私聊测试",
                summary="企业应用工作通知",
                level="success",
                task="私聊测试",
                user_id=1,
                user_name="张三",
                at_user_id="ding-user-1",
            )

        self.assertTrue(sent)
        with self.SessionLocal() as db:
            log = db.query(NotificationLog).one()
            self.assertEqual(log.channel, "dingtalk_work_notice")
            self.assertTrue(log.sent)
            self.assertEqual(log.at_user_id, "ding-user-1")


class DingtalkEnterpriseTests(unittest.TestCase):
    def test_get_access_token_uses_app_key_and_secret(self):
        from integrations.dingtalk.enterprise import clear_token_cache, get_access_token

        clear_token_cache()
        env = {
            "DINGTALK_APP_KEY": "app-key",
            "DINGTALK_APP_SECRET": "app-secret",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("httpx.get") as get:
            get.return_value = httpx.Response(200, json={
                "errcode": 0,
                "access_token": "access-token",
                "expires_in": 7200,
            })

            token = get_access_token()

        self.assertEqual(token, "access-token")
        self.assertEqual(get.call_args.kwargs["params"]["appkey"], "app-key")
        self.assertEqual(get.call_args.kwargs["params"]["appsecret"], "app-secret")

    def test_send_work_notice_posts_corpconversation_message(self):
        from integrations.dingtalk.enterprise import clear_token_cache, send_work_notice

        clear_token_cache()
        env = {
            "DINGTALK_APP_KEY": "app-key",
            "DINGTALK_APP_SECRET": "app-secret",
            "DINGTALK_AGENT_ID": "12345",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("httpx.get") as get, \
             patch("httpx.post") as post:
            get.return_value = httpx.Response(200, json={"errcode": 0, "access_token": "token"})
            post.return_value = httpx.Response(200, json={"errcode": 0, "task_id": 9})

            result = send_work_notice(
                userid="ding-user-1",
                title="标题",
                text="正文",
            )

        self.assertEqual(result["task_id"], 9)
        payload = json.loads(post.call_args.kwargs["content"].decode("utf-8"))
        self.assertEqual(payload["agent_id"], 12345)
        self.assertEqual(payload["userid_list"], "ding-user-1")
        self.assertEqual(payload["msg"]["msgtype"], "markdown")
        self.assertEqual(post.call_args.kwargs["headers"]["Content-Type"], "application/json; charset=utf-8")


class DingtalkOrgSyncTests(unittest.TestCase):
    def setUp(self):
        from db import Base
        import models  # noqa: F401

        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_sync_updates_existing_user_by_name(self):
        from integrations.dingtalk.enterprise import DingTalkUser
        from integrations.dingtalk.org_sync import sync_dingtalk_org
        from models import DingTalkSyncLog, User

        with self.SessionLocal() as db:
            db.add(User(name="张三", department="法务部", role="user", status="active"))
            db.commit()

            env = {
                "DINGTALK_ENTERPRISE_ENABLED": "true",
                "DINGTALK_ORG_SYNC_ENABLED": "true",
            }
            with patch.dict("os.environ", env, clear=True), \
                 patch("integrations.dingtalk.org_sync.fetch_org_users") as fetch:
                fetch.return_value = ([1], [
                    DingTalkUser(
                        userid="ding-user-1",
                        name="张三",
                        unionid="union-1",
                        department=[1, 2],
                        title="法务经理",
                        mobile="13800001234",
                        active=True,
                    )
                ])

                result = sync_dingtalk_org(db=db, root_dept_id=1)

            self.assertEqual(result.status, "ok")
            self.assertEqual(result.matched_count, 1)
            self.assertEqual(result.updated_count, 1)
            user = db.query(User).filter_by(name="张三").one()
            self.assertEqual(user.dingtalk_user_id, "ding-user-1")
            self.assertEqual(user.dingtalk_union_id, "union-1")
            self.assertEqual(user.dingtalk_mobile_tail, "1234")
            log = db.query(DingTalkSyncLog).one()
            self.assertEqual(log.remote_user_count, 1)

    def test_sync_skips_missing_users_by_default(self):
        from integrations.dingtalk.enterprise import DingTalkUser
        from integrations.dingtalk.org_sync import sync_dingtalk_org
        from models import User

        with self.SessionLocal() as db:
            env = {
                "DINGTALK_ENTERPRISE_ENABLED": "true",
                "DINGTALK_ORG_SYNC_ENABLED": "true",
            }
            with patch.dict("os.environ", env, clear=True), \
                 patch("integrations.dingtalk.org_sync.fetch_org_users", return_value=([1], [
                     DingTalkUser(userid="ding-user-2", name="李四")
                 ])):
                result = sync_dingtalk_org(db=db, root_dept_id=1)

            self.assertEqual(result.skipped_count, 1)
            self.assertEqual(db.query(User).count(), 0)


class DingtalkAdminEndpointTests(unittest.TestCase):
    def setUp(self):
        from auth_utils import get_current_user, require_admin
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
            db.add(User(
                name="管理员",
                department="法务部",
                role="admin",
                status="active",
                dingtalk_user_id="ding-admin",
            ))
            db.commit()

        self.user = User(
            id=1,
            name="管理员",
            department="法务部",
            role="admin",
            status="active",
            dingtalk_user_id="ding-admin",
        )
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

    def test_admin_can_send_dingtalk_test_notification(self):
        with patch("routers.admin_users.send_dingtalk_notification", return_value=True) as send:
            r = self.client.post("/api/admin/dingtalk/test-notification")

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["user_name"], "管理员")
        self.assertEqual(send.call_args.kwargs["at_user_id"], "ding-admin")

    def test_admin_can_send_dingtalk_work_notice_test(self):
        with patch("routers.admin_users.send_dingtalk_notification", return_value=True) as send:
            r = self.client.post("/api/admin/dingtalk/test-work-notice")

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})
        self.assertEqual(send.call_args.kwargs["task"], "钉钉私聊通知测试")
        self.assertEqual(send.call_args.kwargs["at_user_id"], "ding-admin")

    def test_admin_users_include_and_update_dingtalk_user_id(self):
        r = self.client.get("/api/admin/users")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["users"][0]["dingtalk_user_id"], "ding-admin")

        patch_r = self.client.patch("/api/admin/users/1", json={"dingtalk_user_id": "ding-new"})
        self.assertEqual(patch_r.status_code, 200)

        updated = self.client.get("/api/admin/users").json()["users"][0]
        self.assertEqual(updated["dingtalk_user_id"], "ding-new")

    def test_admin_can_list_dingtalk_notification_logs(self):
        from models import NotificationLog

        with self.SessionLocal() as db:
            db.add(NotificationLog(
                task="培训信息识别",
                level="error",
                stage="AI 识别",
                title="培训信息识别失败",
                summary="模型超时",
                user_id=1,
                user_name="管理员",
                sent=False,
                skipped_reason=None,
                http_status=None,
                provider_code=None,
                provider_message=None,
                error="timeout",
            ))
            db.commit()

        r = self.client.get("/api/admin/dingtalk/notification-logs")
        self.assertEqual(r.status_code, 200)
        log = r.json()["logs"][0]
        self.assertEqual(log["task"], "培训信息识别")
        self.assertEqual(log["level"], "error")
        self.assertEqual(log["stage"], "AI 识别")
        self.assertFalse(log["sent"])

    def test_admin_can_sync_dingtalk_users(self):
        with patch("routers.admin_users.sync_dingtalk_org") as sync:
            sync.return_value.__dict__ = {
                "status": "ok",
                "root_dept_id": 1,
                "department_count": 1,
                "remote_user_count": 2,
                "matched_count": 1,
                "created_count": 0,
                "updated_count": 1,
                "skipped_count": 1,
                "error": "",
            }
            r = self.client.post("/api/admin/dingtalk/sync-users", json={"root_dept_id": 1})

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["updated_count"], 1)
        sync.assert_called_once()


class DingtalkSsoEndpointTests(unittest.TestCase):
    def setUp(self):
        from auth_utils import get_current_user, require_admin
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
            db.add(User(
                name="张三",
                department="法务部",
                role="user",
                status="active",
                dingtalk_user_id="ding-user-1",
                dingtalk_union_id="union-1",
            ))
            db.commit()

        def override_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_db
        self.app.dependency_overrides.pop(get_current_user, None)
        self.app.dependency_overrides.pop(require_admin, None)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_sso_config_reports_enabled_and_corp_id(self):
        env = {
            "DINGTALK_ENTERPRISE_ENABLED": "true",
            "DINGTALK_SSO_ENABLED": "true",
            "DINGTALK_CORP_ID": "corp-1",
        }
        with patch.dict("os.environ", env, clear=True):
            r = self.client.get("/api/auth/dingtalk/config")

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"enabled": True, "corp_id": "corp-1"})

    def test_sso_rejects_when_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            r = self.client.post("/api/auth/dingtalk/sso", json={"code": "auth-code"})

        self.assertEqual(r.status_code, 403)

    def test_sso_logs_in_bound_user(self):
        from integrations.dingtalk.enterprise import DingTalkAuthUser

        env = {
            "DINGTALK_ENTERPRISE_ENABLED": "true",
            "DINGTALK_SSO_ENABLED": "true",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("routers.auth.get_userinfo_by_code", return_value=DingTalkAuthUser(
                 userid="ding-user-1",
                 name="张三",
                 unionid="union-1",
             )):
            r = self.client.post("/api/auth/dingtalk/sso", json={"code": "auth-code"})

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user"]["name"], "张三")
        self.assertIn("sid=", r.headers.get("set-cookie", ""))


if __name__ == "__main__":
    unittest.main()
