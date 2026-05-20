from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env", override=True)
except Exception:
    pass


def main() -> int:
    from sqlalchemy import inspect
    from db import engine, init_db

    init_db()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {
        "users",
        "sessions",
        "audit_logs",
        "notification_logs",
        "dingtalk_sync_logs",
    }
    missing = sorted(expected - tables)

    print(f"main_db_url = {engine.url.render_as_string(hide_password=True)}")
    print(f"main_db_backend = {engine.url.get_backend_name()}")
    print(f"tables_present = {', '.join(sorted(expected & tables))}")
    if missing:
        print(f"missing_tables = {', '.join(missing)}")
        return 1
    print("[PASS] main DB is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
