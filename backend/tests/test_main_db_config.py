import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


class MainDatabaseConfigTests(unittest.TestCase):
    def test_default_database_url_keeps_sqlite_auth_db(self):
        import db

        with patch.dict(os.environ, {}, clear=True):
            url = db.get_database_url()

        self.assertTrue(url.startswith("sqlite:///"))
        self.assertTrue(url.endswith("auth.db"))

    def test_app_database_url_takes_precedence_over_database_url(self):
        import db

        env = {
            "APP_DATABASE_URL": "postgresql://app:secret@db/app",
            "DATABASE_URL": "postgresql://audit:secret@db/audit",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(db.get_database_url(), "postgresql://app:secret@db/app")

    def test_bare_postgresql_url_uses_psycopg_driver(self):
        import db

        normalized = db._normalize_database_url("postgresql://app:secret@db/app")

        self.assertEqual(normalized, "postgresql+psycopg://app:secret@db/app")

    def test_sqlite_engine_uses_sqlite_backend(self):
        import db

        engine = db.build_engine("sqlite:///:memory:")
        try:
            self.assertEqual(engine.url.get_backend_name(), "sqlite")
        finally:
            engine.dispose()

    def test_main_session_does_not_expire_objects_on_commit(self):
        import db

        self.assertFalse(db.SessionLocal.kw["expire_on_commit"])


if __name__ == "__main__":
    unittest.main()
