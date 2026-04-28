"""Database engine and session management."""

import logging
import re
import sqlite3
from pathlib import Path
from collections.abc import Generator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from ai_trend_monitor.config import DATABASE_PATH

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

logger = logging.getLogger(__name__)

# Expected columns per table. Maps table -> list of (column_name, column_def).
# column_def is the SQLite type + default used in ALTER TABLE ADD COLUMN.
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "topic": [
        ("sources", "TEXT DEFAULT 'reddit'"),
        ("velocity_1h", "REAL DEFAULT 0.0"),
        ("velocity_6h", "REAL DEFAULT 0.0"),
        ("velocity_24h", "REAL DEFAULT 0.0"),
        ("is_official", "INTEGER DEFAULT 0"),
        ("dismissed_at", "TEXT DEFAULT NULL"),
        ("dismiss_action", "TEXT DEFAULT NULL"),
        ("notified_at", "TEXT DEFAULT NULL"),
        ("embedding", "BLOB DEFAULT NULL"),
    ],
}


def get_engine():
    """Create and return the SQLAlchemy engine, ensuring the data directory exists."""
    db_path = Path(DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLModel session."""
    engine = get_engine()
    with Session(engine) as session:
        yield session


def _migrate_schema() -> None:
    """Add missing columns to existing tables. Safe to run repeatedly."""
    db_path = Path(DATABASE_PATH)
    if not db_path.exists():
        return  # Fresh DB, create_all will handle it

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        for table, columns in _MIGRATIONS.items():
            # Validate identifiers to prevent SQL injection
            if not _IDENTIFIER_RE.match(table):
                raise ValueError(f"Invalid table name: {table}")

            # Get existing columns — PRAGMA doesn't support parameters,
            # so we whitelist-validate the identifier above.
            cursor.execute("PRAGMA table_info(%s)" % table)  # noqa: S608  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query  # identifier validated by regex
            existing = {row[1] for row in cursor.fetchall()}

            if not existing:
                continue  # Table doesn't exist yet

            for col_name, col_def in columns:
                if col_name not in existing:
                    if not _IDENTIFIER_RE.match(col_name):
                        raise ValueError(f"Invalid column name: {col_name}")
                    stmt = "ALTER TABLE %s ADD COLUMN %s %s" % (  # noqa: S608
                        table,
                        col_name,
                        col_def,
                    )
                    cursor.execute(stmt)  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query  # identifier validated by regex
                    logger.info("Migration: added %s.%s", table, col_name)

        conn.commit()
        conn.close()
    except Exception:
        logger.exception("Schema migration failed (non-fatal)")


def init_db() -> None:
    """Create all tables and migrate existing schema if needed."""
    _migrate_schema()

    from ai_trend_monitor import models  # noqa: F401

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
