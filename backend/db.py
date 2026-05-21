import os
from pathlib import Path
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker, DeclarativeBase

_DATA_DIR = Path(__file__).parent.parent / "data"
_DATA_DIR.mkdir(exist_ok=True)


def _configure_sqlite(dbapi_conn, _connection_record):
    """启用 WAL 模式 + 5 秒忙等待：允许多连接并发读写，避免 SQLITE_BUSY 阻塞。"""
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA busy_timeout=5000")


def get_database_url() -> str:
    """Main application database URL.

    APP_DATABASE_URL is preferred so the main business DB can be configured
    independently from LLM_AUDIT_DATABASE_URL. DATABASE_URL remains a fallback
    for older deployments. If neither is set, keep the existing SQLite file.
    """
    return (
        os.getenv("APP_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or f"sqlite:///{_DATA_DIR / 'auth.db'}"
    )


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _is_sqlite(engine: Engine) -> bool:
    return engine.url.get_backend_name() == "sqlite"


def _is_postgresql(engine: Engine) -> bool:
    return engine.url.get_backend_name() == "postgresql"


def build_engine(url: str | None = None) -> Engine:
    raw_url = url or get_database_url()
    normalized = _normalize_database_url(raw_url)
    parsed = make_url(normalized)
    if parsed.get_backend_name() == "sqlite":
        db_engine = create_engine(normalized, connect_args={"check_same_thread": False})
        event.listen(db_engine, "connect", _configure_sqlite)
        return db_engine
    return create_engine(
        normalized,
        pool_pre_ping=True,
        pool_size=int(os.getenv("APP_DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("APP_DB_MAX_OVERFLOW", "5")),
    )


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import models  # noqa: F401 — register core models before create_all
    if _is_postgresql(engine):
        _drop_orphan_pg_sequences()
    Base.metadata.create_all(engine)
    if _is_sqlite(engine):
        _migrate_auth_schema()
    _seed()
    # llm_traces lives in a separate database (PostgreSQL). Initialise it
    # but don't let its failure break app startup — tracing degrades to
    # NoopTracer when the audit DB is unreachable.
    try:
        from llm_audit.db import init_audit_db
        if init_audit_db():
            import logging
            logging.getLogger(__name__).info("llm_audit DB initialised")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("llm_audit DB init failed (non-fatal)")


def _migrate_auth_schema():
    """Apply tiny SQLite auth DB migrations not covered by create_all()."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "dingtalk_user_id" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN dingtalk_user_id VARCHAR(100)"))
        if "dingtalk_union_id" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN dingtalk_union_id VARCHAR(100)"))
        if "dingtalk_dept_ids" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN dingtalk_dept_ids VARCHAR(300)"))
        if "dingtalk_title" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN dingtalk_title VARCHAR(100)"))
        if "dingtalk_mobile_tail" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN dingtalk_mobile_tail VARCHAR(8)"))
        if "dingtalk_active" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN dingtalk_active BOOLEAN"))
        if "dingtalk_synced_at" not in columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN dingtalk_synced_at DATETIME"))


def _drop_orphan_pg_sequences():
    """Clean up sequences left behind by an interrupted first create_all().

    PostgreSQL can keep `*_id_seq` after a failed CREATE TABLE transaction in
    some deployment attempts. We only drop a known sequence when its owning
    table does not exist, so existing data is never touched.
    """
    tables = [
        "users",
        "sessions",
        "audit_logs",
        "notification_logs",
        "dingtalk_sync_logs",
        "background_tasks",
    ]
    with engine.begin() as conn:
        for table_name in tables:
            table_exists = conn.execute(text("SELECT to_regclass(:name)"), {"name": table_name}).scalar()
            seq_name = f"{table_name}_id_seq"
            seq_exists = conn.execute(text("SELECT to_regclass(:name)"), {"name": seq_name}).scalar()
            if not table_exists and seq_exists:
                conn.execute(text(f'DROP SEQUENCE IF EXISTS "{seq_name}"'))


def _seed():
    """创建初始管理员（仅当数据库为空时）。"""
    import secrets
    import hashlib
    from models import User

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            code = str(1000 + secrets.randbelow(9000))
            admin = User(
                name="管理员",
                department="法务部",
                role="admin",
                status="active",
                short_code_hash=hashlib.sha256(code.encode()).hexdigest(),
            )
            db.add(admin)
            db.commit()
            sep = "=" * 52
            print(f"\n{sep}")
            print("[Auth] 初始管理员账号已创建")
            print(f"[Auth] 姓名：管理员   短码：{code}")
            print("[Auth] 请登录后在「用户管理」面板新增实际用户并重置短码")
            print(f"{sep}\n")
    finally:
        db.close()
