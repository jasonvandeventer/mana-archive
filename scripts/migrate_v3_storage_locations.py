"""Idempotent v3/v3.1 SQLite migration for Mana Archive.

This migration handles two related schema transitions:

1. v3.0 storage-location foundation
   - users table
   - storage_locations table
   - inventory_rows.user_id
   - inventory_rows.storage_location_id

2. v3.1 multi-user ownership expansion
   - decks.user_id
   - import_batches.user_id
   - transaction_logs.user_id

The script is intentionally defensive:
- it refuses to run against unexpected SQLite paths
- it checks columns directly instead of trusting a coarse "migration applied" flag
- it preserves inventory row count and total quantity
- it validates that all user-owned rows are backfilled
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Base, engine

DEFAULT_USERNAME = "jason.v"
DEFAULT_PASSWORD_HASH = "CHANGE_ME_V3_BOOTSTRAP"

ALLOWED_DATABASE_URLS = {
    "sqlite:////tmp/mana_archive.db",
    "sqlite:////data/mana_archive.db",
    "sqlite:///dev-data/mana_archive.db",
}


# =============================================================================
# Introspection helpers
# =============================================================================


def column_exists(table_name: str, column_name: str) -> bool:
    """Return True if a column exists on a table."""
    inspector = inspect(engine)
    return column_name in [col["name"] for col in inspector.get_columns(table_name)]


def table_exists(table_name: str) -> bool:
    """Return True if a table exists."""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def scalar(conn, sql: str, params: dict | None = None):
    """Run a scalar SQL query through SQLAlchemy text()."""
    return conn.execute(text(sql), params or {}).scalar()


def add_column_if_missing(conn, table_name: str, column_name: str, column_sql: str) -> None:
    """Add a SQLite column only if it does not already exist."""
    if column_exists(table_name, column_name):
        return

    print(f"Adding {table_name}.{column_name}")
    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))


# =============================================================================
# Migration state and validation
# =============================================================================


def schema_is_complete() -> bool:
    """Return True only when every v3/v3.1 column exists."""
    required_columns = [
        ("inventory_rows", "user_id"),
        ("inventory_rows", "storage_location_id"),
        ("decks", "user_id"),
        ("import_batches", "user_id"),
        ("transaction_logs", "user_id"),
    ]

    return all(column_exists(table, column) for table, column in required_columns)


def data_is_backfilled(conn) -> bool:
    """Return True only when user-owned rows have no missing user_id values."""
    checks = [
        "SELECT COUNT(*) FROM inventory_rows WHERE user_id IS NULL",
        "SELECT COUNT(*) FROM decks WHERE user_id IS NULL",
        "SELECT COUNT(*) FROM import_batches WHERE user_id IS NULL",
        "SELECT COUNT(*) FROM transaction_logs WHERE user_id IS NULL",
    ]

    missing_counts = [scalar(conn, sql) for sql in checks]
    return all(count == 0 for count in missing_counts)


def validate_final_state(conn, before_rows: int, before_qty: int) -> None:
    """Validate that the migration preserved inventory and completed ownership backfill."""
    after_rows = scalar(conn, "SELECT COUNT(*) FROM inventory_rows")
    after_qty = scalar(conn, "SELECT COALESCE(SUM(quantity), 0) FROM inventory_rows")

    if before_rows != after_rows:
        raise RuntimeError(f"Inventory row count changed: before={before_rows}, after={after_rows}")

    if before_qty != after_qty:
        raise RuntimeError(f"Inventory quantity changed: before={before_qty}, after={after_qty}")

    missing_inventory_users = scalar(
        conn,
        "SELECT COUNT(*) FROM inventory_rows WHERE user_id IS NULL",
    )
    missing_locations = scalar(
        conn,
        "SELECT COUNT(*) FROM inventory_rows WHERE storage_location_id IS NULL",
    )
    missing_decks = scalar(conn, "SELECT COUNT(*) FROM decks WHERE user_id IS NULL")
    missing_imports = scalar(conn, "SELECT COUNT(*) FROM import_batches WHERE user_id IS NULL")
    missing_logs = scalar(conn, "SELECT COUNT(*) FROM transaction_logs WHERE user_id IS NULL")

    if missing_inventory_users != 0:
        raise RuntimeError(f"Inventory rows missing user_id: {missing_inventory_users}")

    if missing_locations != 0:
        raise RuntimeError(f"Inventory rows missing storage_location_id: {missing_locations}")

    if missing_decks != 0:
        raise RuntimeError(f"Decks missing user_id: {missing_decks}")

    if missing_imports != 0:
        raise RuntimeError(f"Import batches missing user_id: {missing_imports}")

    if missing_logs != 0:
        raise RuntimeError(f"Transaction logs missing user_id: {missing_logs}")

    print("Migration validation passed.")
    print(f"After inventory rows: {after_rows}")
    print(f"After inventory quantity: {after_qty}")


# =============================================================================
# User and storage-location bootstrap
# =============================================================================


def get_or_create_default_user(conn) -> int:
    """Return the default bootstrap user's id, creating it if needed."""
    user_id = scalar(
        conn,
        "SELECT id FROM users WHERE username = :username",
        {"username": DEFAULT_USERNAME},
    )

    if user_id is not None:
        return int(user_id)

    print(f"Creating default user: {DEFAULT_USERNAME}")
    conn.execute(
        text(
            """
            INSERT INTO users (username, password_hash, created_at)
            VALUES (:username, :password_hash, CURRENT_TIMESTAMP)
            """
        ),
        {
            "username": DEFAULT_USERNAME,
            "password_hash": DEFAULT_PASSWORD_HASH,
        },
    )

    user_id = scalar(
        conn,
        "SELECT id FROM users WHERE username = :username",
        {"username": DEFAULT_USERNAME},
    )

    if user_id is None:
        raise RuntimeError(f"Failed to create default user: {DEFAULT_USERNAME}")

    return int(user_id)


def get_or_create_root_location(conn, user_id: int) -> int:
    """Return the user's root storage location id, creating it if needed."""
    root_id = scalar(
        conn,
        """
        SELECT id FROM storage_locations
        WHERE user_id = :user_id
          AND parent_id IS NULL
          AND type = 'root'
          AND name = 'Root'
        """,
        {"user_id": user_id},
    )

    if root_id is not None:
        return int(root_id)

    print("Creating root storage location")
    conn.execute(
        text(
            """
            INSERT INTO storage_locations
                (user_id, name, type, parent_id, sort_order, created_at)
            VALUES
                (:user_id, 'Root', 'root', NULL, 0, CURRENT_TIMESTAMP)
            """
        ),
        {"user_id": user_id},
    )

    root_id = scalar(
        conn,
        """
        SELECT id FROM storage_locations
        WHERE user_id = :user_id
          AND parent_id IS NULL
          AND type = 'root'
          AND name = 'Root'
        """,
        {"user_id": user_id},
    )

    if root_id is None:
        raise RuntimeError("Failed to create root storage location")

    return int(root_id)


def get_or_create_drawer_locations(conn, user_id: int, root_id: int) -> dict[str, int]:
    """Return drawer number -> storage_location.id for Drawers 1-6."""
    drawer_location_ids: dict[str, int] = {}

    for drawer in ["1", "2", "3", "4", "5", "6"]:
        name = f"Drawer {drawer}"

        location_id = scalar(
            conn,
            """
            SELECT id FROM storage_locations
            WHERE user_id = :user_id
              AND name = :name
              AND type = 'drawer'
            """,
            {"user_id": user_id, "name": name},
        )

        if location_id is None:
            print(f"Creating storage location: {name}")
            conn.execute(
                text(
                    """
                    INSERT INTO storage_locations
                        (user_id, name, type, parent_id, sort_order, created_at)
                    VALUES
                        (:user_id, :name, 'drawer', :parent_id, :sort_order, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "user_id": user_id,
                    "name": name,
                    "parent_id": root_id,
                    "sort_order": int(drawer),
                },
            )

            location_id = scalar(
                conn,
                """
                SELECT id FROM storage_locations
                WHERE user_id = :user_id
                  AND name = :name
                  AND type = 'drawer'
                """,
                {"user_id": user_id, "name": name},
            )

        if location_id is None:
            raise RuntimeError(f"Failed to create storage location: {name}")

        drawer_location_ids[drawer] = int(location_id)

    return drawer_location_ids


# =============================================================================
# Schema mutation and backfill
# =============================================================================


def add_missing_columns(conn) -> None:
    """Add all v3/v3.1 columns that are not already present."""
    add_column_if_missing(
        conn,
        table_name="inventory_rows",
        column_name="user_id",
        column_sql="user_id INTEGER",
    )
    add_column_if_missing(
        conn,
        table_name="inventory_rows",
        column_name="storage_location_id",
        column_sql="storage_location_id INTEGER",
    )
    add_column_if_missing(
        conn,
        table_name="decks",
        column_name="user_id",
        column_sql="user_id INTEGER",
    )
    add_column_if_missing(
        conn,
        table_name="import_batches",
        column_name="user_id",
        column_sql="user_id INTEGER",
    )
    add_column_if_missing(
        conn,
        table_name="transaction_logs",
        column_name="user_id",
        column_sql="user_id INTEGER",
    )


def backfill_user_owned_tables(conn, user_id: int) -> None:
    """Backfill user_id onto every existing user-owned table."""
    print("Backfilling inventory_rows.user_id")
    conn.execute(
        text(
            """
            UPDATE inventory_rows
            SET user_id = :user_id
            WHERE user_id IS NULL
            """
        ),
        {"user_id": user_id},
    )

    print("Backfilling decks.user_id")
    conn.execute(
        text(
            """
            UPDATE decks
            SET user_id = :user_id
            WHERE user_id IS NULL
            """
        ),
        {"user_id": user_id},
    )

    print("Backfilling import_batches.user_id")
    conn.execute(
        text(
            """
            UPDATE import_batches
            SET user_id = :user_id
            WHERE user_id IS NULL
            """
        ),
        {"user_id": user_id},
    )

    print("Backfilling transaction_logs.user_id")
    conn.execute(
        text(
            """
            UPDATE transaction_logs
            SET user_id = :user_id
            WHERE user_id IS NULL
            """
        ),
        {"user_id": user_id},
    )


def backfill_inventory_storage_locations(conn, drawer_location_ids: dict[str, int]) -> None:
    """Backfill inventory_rows.storage_location_id from legacy drawer values."""
    print("Backfilling inventory_rows.storage_location_id from drawer")

    for drawer, location_id in drawer_location_ids.items():
        conn.execute(
            text(
                """
                UPDATE inventory_rows
                SET storage_location_id = :location_id
                WHERE drawer = :drawer
                  AND storage_location_id IS NULL
                """
            ),
            {"drawer": drawer, "location_id": location_id},
        )


# =============================================================================
# Entrypoint
# =============================================================================


def main() -> None:
    if str(engine.url) not in ALLOWED_DATABASE_URLS:
        raise RuntimeError(f"Refusing to run migration against unexpected DB: {engine.url}")

    print(f"Using database: {engine.url}")

    # Ensure model-defined tables exist before column introspection/backfill.
    Base.metadata.create_all(bind=engine)

    required_tables = [
        "users",
        "storage_locations",
        "inventory_rows",
        "decks",
        "import_batches",
        "transaction_logs",
    ]

    missing_tables = [table for table in required_tables if not table_exists(table)]
    if missing_tables:
        raise RuntimeError(f"Required tables missing after create_all: {missing_tables}")

    with engine.begin() as conn:
        before_rows = scalar(conn, "SELECT COUNT(*) FROM inventory_rows")
        before_qty = scalar(conn, "SELECT COALESCE(SUM(quantity), 0) FROM inventory_rows")

        print(f"Before inventory rows: {before_rows}")
        print(f"Before inventory quantity: {before_qty}")

        if schema_is_complete() and data_is_backfilled(conn):
            print("v3/v3.1 migration already applied. Exiting cleanly.")
            return

        add_missing_columns(conn)

        user_id = get_or_create_default_user(conn)
        root_id = get_or_create_root_location(conn, user_id)
        drawer_location_ids = get_or_create_drawer_locations(conn, user_id, root_id)

        backfill_user_owned_tables(conn, user_id)
        backfill_inventory_storage_locations(conn, drawer_location_ids)

        validate_final_state(conn, before_rows=before_rows, before_qty=before_qty)

        print("Migration complete.")


if __name__ == "__main__":
    main()
