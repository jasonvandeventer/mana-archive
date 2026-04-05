"""Database engine, session factory, and table initialization."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine

from mana_archive.logging_config import get_logger
from mana_archive.models import (  # noqa: F401 – import side-effects register tables
    Card,
    Inventory,
    TransactionLog,
)

log = get_logger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "mana_archive.db")
DB_URL = f"sqlite:///{DB_PATH}"

_engine = None


def get_engine():
    """Return the singleton SQLAlchemy engine, creating it on first call."""
    global _engine
    if _engine is None:
        os.makedirs(DB_DIR, exist_ok=True)
        _engine = create_engine(
            DB_URL,
            echo=False,
            connect_args={"check_same_thread": False},
        )
        # Enable WAL mode for better concurrent read performance under Streamlit
        @event.listens_for(_engine, "connect")
        def set_wal_mode(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        log.info("SQLite engine created at %s", DB_PATH)
    return _engine


def init_db() -> None:
    """Create all tables and apply lightweight column migrations."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)

    # Incremental column migrations for existing databases.
    # SQLite supports ADD COLUMN but not DROP/MODIFY, so each migration is
    # a simple try/except – the error is silently swallowed if the column
    # already exists.
    _column_migrations = [
        "ALTER TABLE transaction_log ADD COLUMN batch_id TEXT",
        "ALTER TABLE card ADD COLUMN price_source TEXT",
        "ALTER TABLE card ADD COLUMN price_last_updated_at TIMESTAMP",
    ]
    with engine.connect() as conn:
        for stmt in _column_migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
                log.info("Migration applied: %s", stmt)
            except Exception:
                pass  # Column already exists

    log.info("Database tables created / verified.")


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a database session and commit on success, rollback on error."""
    with Session(get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
