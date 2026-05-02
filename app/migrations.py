from sqlalchemy import text

from app.db import engine


def ensure_migrations_table():
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )


def has_migration(conn, name: str) -> bool:
    result = conn.execute(
        text("SELECT 1 FROM schema_migrations WHERE name = :name"),
        {"name": name},
    ).fetchone()
    return result is not None


def record_migration(conn, name: str):
    conn.execute(
        text("INSERT INTO schema_migrations (name) VALUES (:name)"),
        {"name": name},
    )
