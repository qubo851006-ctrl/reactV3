from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import MetaData, Table, create_engine, delete, func, insert, select

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env", override=True)
except Exception:
    pass

TABLE_ORDER = [
    "users",
    "sessions",
    "audit_logs",
    "notification_logs",
    "dingtalk_sync_logs",
]


def _source_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _table_count(conn, table: Table) -> int:
    return int(conn.execute(select(func.count()).select_from(table)).scalar() or 0)


def _reset_pg_sequence(conn, table: Table) -> None:
    if conn.engine.url.get_backend_name() != "postgresql":
        return
    if "id" not in table.c:
        return
    max_id = conn.execute(select(func.max(table.c.id))).scalar()
    if max_id is None:
        return
    conn.exec_driver_sql(
        "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, true)",
        (table.name, int(max_id)),
    )


def migrate(source: Path, dry_run: bool, force: bool) -> int:
    from db import Base, build_engine, get_database_url
    import models  # noqa: F401

    target_url = get_database_url()
    if target_url.startswith("sqlite") and not dry_run:
        print("Refusing to migrate: APP_DATABASE_URL/DATABASE_URL does not point to PostgreSQL.")
        print(f"Current main DB URL: {target_url}")
        return 2
    if not source.exists():
        print(f"Source SQLite DB not found: {source}")
        return 2

    source_engine = create_engine(_source_url(source), connect_args={"check_same_thread": False})
    if target_url.startswith("sqlite") and dry_run:
        source_meta = MetaData()
        try:
            with source_engine.connect() as src:
                source_meta.reflect(bind=src, only=lambda name, _: name in TABLE_ORDER)
                for name in TABLE_ORDER:
                    if name in source_meta.tables:
                        count = _table_count(src, source_meta.tables[name])
                        print(f"[DRY-RUN] {name}: {count} rows")
            print("[DRY-RUN] APP_DATABASE_URL/DATABASE_URL is not PostgreSQL; no target DB checked")
            return 0
        finally:
            source_engine.dispose()

    target_engine = build_engine(target_url)
    Base.metadata.create_all(target_engine)

    source_meta = MetaData()
    target_meta = Base.metadata
    copied: dict[str, int] = {}

    try:
        with source_engine.connect() as src, target_engine.begin() as dst:
            source_meta.reflect(bind=src, only=lambda name, _: name in TABLE_ORDER)
            target_tables = {table.name: table for table in target_meta.sorted_tables if table.name in TABLE_ORDER}

            existing = {
                name: _table_count(dst, target_tables[name])
                for name in TABLE_ORDER
                if name in target_tables
            }
            occupied = {name: count for name, count in existing.items() if count > 0}
            if occupied and not force:
                print("Target main DB already contains data; refusing to overwrite.")
                print(f"Existing rows: {occupied}")
                print("Re-run with --force only after taking a backup.")
                return 3

            if dry_run:
                for name in TABLE_ORDER:
                    if name in source_meta.tables:
                        count = _table_count(src, source_meta.tables[name])
                        print(f"[DRY-RUN] {name}: {count} rows")
                print("[DRY-RUN] no data was written")
                return 0

            if force:
                for name in reversed(TABLE_ORDER):
                    table = target_tables.get(name)
                    if table is not None:
                        dst.execute(delete(table))

            for name in TABLE_ORDER:
                source_table = source_meta.tables.get(name)
                target_table = target_tables.get(name)
                if source_table is None or target_table is None:
                    copied[name] = 0
                    continue

                target_cols = set(target_table.c.keys())
                rows = []
                for row in src.execute(select(source_table)).mappings():
                    rows.append({k: v for k, v in row.items() if k in target_cols})

                if rows:
                    dst.execute(insert(target_table), rows)
                    _reset_pg_sequence(dst, target_table)
                copied[name] = len(rows)
    finally:
        source_engine.dispose()
        target_engine.dispose()

    print(f"Migrated rows: {copied}")
    print("[PASS] SQLite main DB copied to PostgreSQL")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy V3 main DB data from data/auth.db SQLite to APP_DATABASE_URL PostgreSQL.")
    parser.add_argument("--source", default=str(ROOT / "data" / "auth.db"), help="Source SQLite auth.db path")
    parser.add_argument("--execute", action="store_true", help="Write data to target DB. Without this, dry-run only.")
    parser.add_argument("--force", action="store_true", help="Clear target tables before inserting. Requires a backup.")
    args = parser.parse_args()

    return migrate(Path(args.source), dry_run=not args.execute, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
