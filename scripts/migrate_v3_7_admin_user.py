from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def main() -> None:
    print(f"Using database: {engine.url}")

    with engine.begin() as conn:
        if not column_exists(conn, "users", "is_admin"):
            conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"))
            print("Added users.is_admin column")
        else:
            print("users.is_admin already exists, skipping")

        # Seed the first admin — idempotent, safe to re-run
        conn.execute(text("UPDATE users SET is_admin = 1 WHERE username = 'jason.v'"))
        print("Ensured jason.v has is_admin = true")

    print("Migration complete.")


if __name__ == "__main__":
    main()
