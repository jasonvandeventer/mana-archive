from __future__ import annotations

from sqlalchemy import text

from app.db import engine


def table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table_name},
    ).fetchone()
    return result is not None


def main() -> None:
    print(f"Using database: {engine.url}")

    with engine.begin() as conn:
        if table_exists(conn, "deck_items"):
            count = conn.execute(text("SELECT COUNT(*) FROM deck_items")).scalar()
            if count > 0:
                print(
                    f"WARNING: {count} unmigrated rows in deck_items — should have been migrated in v3.4"
                )
            conn.execute(text("DROP TABLE deck_items"))
            print("Dropped deck_items table")
        else:
            print("deck_items table does not exist, skipping")

    print("Migration complete.")


if __name__ == "__main__":
    main()
