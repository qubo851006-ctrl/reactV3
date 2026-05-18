"""Standalone database engine for the llm_traces table.

Why separate from the main app DB:
- Audit data has a different cardinality (every LLM call = 1 row) and
  retention profile (we may rotate or archive) than auth/session/audit_logs.
- Moving llm_traces to PostgreSQL is the first step of P0-1; the rest of
  the app remains on SQLite until business-data migration lands.
- Decoupling means an audit-DB outage cannot break login or the rest of
  the app — the tracer fails open.

Configuration:
    LLM_AUDIT_DATABASE_URL  — explicit override (preferred)
    DATABASE_URL            — fallback (shared with future P0-1 migrations)

If neither is set or the connection fails at startup, callers fall back to
NoopTracer (see llm_audit.__init__.get_tracer).

Driver: psycopg v3 via `postgresql+psycopg://`. Pool sizing kept conservative
because each request typically opens one short-lived span.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


logger = logging.getLogger(__name__)


class AuditBase(DeclarativeBase):
    """Independent metadata so the audit table isn't tied to the app's
    SQLite create_all flow."""


def _resolve_audit_url() -> str | None:
    url = os.getenv("LLM_AUDIT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        return None
    # SQLAlchemy needs an explicit driver tag for psycopg v3; the bare
    # `postgresql://` URL would try psycopg2 first.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _build_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite"):
        # SQLite path (tests use this); replicate main db.py PRAGMAs.
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _wal(conn, _rec):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")

        return engine
    # PostgreSQL (production target).
    return create_engine(
        url,
        pool_pre_ping=True,       # detect dropped connections from PG-side timeouts
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,        # recycle every 30min to dodge idle-kill firewalls
    )


# Lazy-initialised engine. Tests can call set_audit_engine() to inject a
# tempfile SQLite engine.
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_audit_engine() -> Engine | None:
    """Return the configured engine, building it lazily. Returns None if no
    URL is configured, the driver is missing, or the engine can't be built —
    callers treat tracing as unavailable."""
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    url = _resolve_audit_url()
    if not url:
        logger.warning("LLM_AUDIT_DATABASE_URL/DATABASE_URL not set; tracing disabled")
        return None
    try:
        _engine = _build_engine(url)
    except ModuleNotFoundError as e:
        logger.warning(
            "audit DB driver missing (%s); tracing disabled. "
            "Run: pip install 'psycopg[binary]==3.2.3'", e,
        )
        return None
    except Exception:
        logger.exception("failed to build audit engine; tracing disabled")
        return None
    _SessionLocal = sessionmaker(bind=_engine)
    return _engine


def get_audit_session_factory() -> sessionmaker | None:
    """Return the sessionmaker, initialising the engine if needed."""
    if _SessionLocal is None:
        get_audit_engine()
    return _SessionLocal


def set_audit_engine(engine: Engine, session_factory: sessionmaker | None = None) -> None:
    """Override the engine — used by tests to inject SQLite tempfile DBs."""
    global _engine, _SessionLocal
    _engine = engine
    _SessionLocal = session_factory or sessionmaker(bind=engine)


def reset_audit_engine() -> None:
    """Reset to lazy state so the next get_audit_engine() rebuilds from env."""
    global _engine, _SessionLocal
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            logger.exception("failed to dispose audit engine")
    _engine = None
    _SessionLocal = None


def init_audit_db() -> bool:
    """Create the llm_traces table if it doesn't exist. Returns True on
    success, False if tracing should be considered disabled."""
    import llm_audit.models  # noqa: F401 — register tables on AuditBase

    engine = get_audit_engine()
    if engine is None:
        return False
    try:
        AuditBase.metadata.create_all(engine)
        return True
    except Exception:
        logger.exception("failed to create llm_traces table")
        return False
