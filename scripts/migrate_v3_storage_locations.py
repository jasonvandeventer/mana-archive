from __future__ import annotations

from sqlalchemy import inspect, text

from app.db import Base, engine

DEFAULT_USERNAME = "jason.v"
DEFAULT_PASSWORD_HASH = "CHANGE_ME_V3_BOOTSTRAP"


def column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(engine)
    return column_name in [col["name"] for col in inspector.get_columns(table_name)]


def scalar(conn, sql: str, params: dict | None = None):
    return conn.execute(text(sql), params or {}).scalar()


def main() -> None:
    allowed_urls = {
        "sqlite:////tmp/mana_archive.db",
        "sqlite:////data/mana_archive.db",
    }   

    if str(engine.url) not in allowed_urls:
        raise RuntimeError(f"Refusing to run migration against unexpected DB: {engine.url}")


    print(f"Using database: {engine.url}")

    # Create new v3 tables.
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        before_rows = scalar(conn, "SELECT COUNT(*) FROM inventory_rows")
        before_qty = scalar(conn, "SELECT COALESCE(SUM(quantity), 0) FROM inventory_rows")

        print(f"Before inventory rows: {before_rows}")
        print(f"Before inventory quantity: {before_qty}")

        if not column_exists("inventory_rows", "user_id"):
            print("Adding inventory_rows.user_id")
            conn.execute(text("ALTER TABLE inventory_rows ADD COLUMN user_id INTEGER"))

        if not column_exists("inventory_rows", "storage_location_id"):
            print("Adding inventory_rows.storage_location_id")
            conn.execute(text("ALTER TABLE inventory_rows ADD COLUMN storage_location_id INTEGER"))

        user_id = scalar(
            conn,
            "SELECT id FROM users WHERE username = :username",
            {"username": DEFAULT_USERNAME},
        )

        if user_id is None:
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

            drawer_location_ids[drawer] = location_id

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

        after_rows = scalar(conn, "SELECT COUNT(*) FROM inventory_rows")
        after_qty = scalar(conn, "SELECT COALESCE(SUM(quantity), 0) FROM inventory_rows")
        missing_users = scalar(conn, "SELECT COUNT(*) FROM inventory_rows WHERE user_id IS NULL")
        missing_locations = scalar(
            conn,
            "SELECT COUNT(*) FROM inventory_rows WHERE storage_location_id IS NULL",
        )

        if before_rows != after_rows:
            raise RuntimeError(f"Row count changed: before={before_rows}, after={after_rows}")

        if before_qty != after_qty:
            raise RuntimeError(f"Quantity changed: before={before_qty}, after={after_qty}")

        if missing_users != 0:
            raise RuntimeError(f"Rows missing user_id: {missing_users}")

        if missing_locations != 0:
            raise RuntimeError(f"Rows missing storage_location_id: {missing_locations}")

        print("Migration complete.")
        print(f"After inventory rows: {after_rows}")
        print(f"After inventory quantity: {after_qty}")


if __name__ == "__main__":
    main()
