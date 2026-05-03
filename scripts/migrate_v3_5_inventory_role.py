from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def main() -> None:
    print(f"Using database: {engine.url}")

    with engine.begin() as conn:
        if not column_exists(conn, "inventory_rows", "role"):
            conn.execute(text("ALTER TABLE inventory_rows ADD COLUMN role TEXT"))
            print("Added inventory_rows.role column")
        else:
            print("inventory_rows.role already exists, skipping")

    print("Migration complete.")


if __name__ == "__main__":
    main()
