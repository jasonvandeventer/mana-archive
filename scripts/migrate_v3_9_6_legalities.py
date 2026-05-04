from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def main() -> None:
    with engine.begin() as conn:
        if not column_exists(conn, "cards", "legalities"):
            conn.execute(text("ALTER TABLE cards ADD COLUMN legalities TEXT"))
            print("Added legalities column to cards")
        else:
            print("legalities column already exists, skipping")


if __name__ == "__main__":
    main()
