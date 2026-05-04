from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def main() -> None:
    print(f"Using database: {engine.url}")

    with engine.begin() as conn:
        for col, definition in [
            ("colors", "VARCHAR(64)"),
            ("mana_cost", "VARCHAR(128)"),
            ("cmc", "REAL"),
        ]:
            if not column_exists(conn, "cards", col):
                conn.execute(text(f"ALTER TABLE cards ADD COLUMN {col} {definition}"))
                print(f"Added cards.{col}")
            else:
                print(f"cards.{col} already exists, skipping")

    print("Migration v3.8 card attrs complete.")


if __name__ == "__main__":
    main()
