"""Alembic environment for the V3 main DB.

Design choices:
  - Database URL comes from db.py (which already supports APP_DATABASE_URL /
    DATABASE_URL / SQLite fallback). Do NOT set sqlalchemy.url in alembic.ini.
  - target_metadata = Base.metadata so `revision --autogenerate` can diff
    the live DB against current ORM models. All 7 main-DB tables (User,
    UserSession, AuditLog, NotificationLog, DingTalkSyncLog, BackgroundTask)
    are picked up automatically via `import models`.
  - render_as_batch=True for SQLite so future ALTER COLUMN works via
    batch_alter_table (build new table → copy data → swap). No-op on PG.
  - llm_audit tables are intentionally NOT in scope — that DB has its own
    URL (LLM_AUDIT_DATABASE_URL) and will get its own alembic later if needed.
"""
from logging.config import fileConfig
from pathlib import Path
import sys

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make `backend/` importable when alembic runs from `backend/`.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load .env so APP_DATABASE_URL / DATABASE_URL are visible to db.py.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND_DIR / ".env")

# Pull URL + Base.metadata from the same place the live app uses.
from db import Base, get_database_url, _normalize_database_url  # noqa: E402
import models  # noqa: F401, E402  — ensures all main-DB models register on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject runtime URL so alembic.ini stays free of secrets.
_db_url = _normalize_database_url(get_database_url())
config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata

# Tables owned by the llm_audit subsystem. When LLM_AUDIT_DATABASE_URL is
# unset, llm_audit falls back to the main DB, so these physical tables show
# up in the main connection. Without this filter, autogenerate would think
# they are "extra" and propose to DROP them. They get their own alembic
# (or stay on SQLAlchemy create_all) later.
LLM_AUDIT_TABLES = {"llm_traces", "llm_traces_archive"}


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def _include_object(obj, name, type_, reflected, compare_to):
    """Skip llm_audit-owned tables so autogenerate won't try to drop them."""
    if type_ == "table" and name in LLM_AUDIT_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_is_sqlite_url(url),
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        url = str(connection.engine.url)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite_url(url),
            include_object=_include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
