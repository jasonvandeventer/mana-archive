from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def main() -> None:
    print(f"Using database: {engine.url}")

    with engine.begin() as conn:
        if not column_exists(conn, "cards", "color_identity"):
            conn.execute(text("ALTER TABLE cards ADD COLUMN color_identity VARCHAR(64)"))
            print("Added cards.color_identity")
        else:
            print("cards.color_identity already exists, skipping")

    print("Migration v3.8.8 color_identity complete.")


if __name__ == "__main__":
    main()
