from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def main() -> None:
    with engine.begin() as conn:
        if not column_exists(conn, "users", "display_name"):
            conn.execute(text("ALTER TABLE users ADD COLUMN display_name VARCHAR(64)"))
            print("Added display_name column to users")
        else:
            print("display_name column already exists, skipping")


if __name__ == "__main__":
    main()
