from sqlalchemy import inspect, text

from app.db import engine

REQUIRED_COLUMNS = {
    "is_active": "BOOLEAN NOT NULL DEFAULT 1",
    "is_admin": "BOOLEAN NOT NULL DEFAULT 0",
}


def column_exists(table_columns: list[str], column_name: str) -> bool:
    return column_name in table_columns


def main() -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if "users" not in tables:
        raise RuntimeError("Refusing migration: users table does not exist.")

    existing_columns = [column["name"] for column in inspector.get_columns("users")]

    with engine.begin() as conn:
        for column_name, column_definition in REQUIRED_COLUMNS.items():
            if column_exists(existing_columns, column_name):
                print(f"Skipping users.{column_name}; already exists.")
                continue

            print(f"Adding users.{column_name}...")
            conn.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}"))

        conn.execute(text("UPDATE users SET is_active = 1 WHERE is_active IS NULL"))
        conn.execute(text("UPDATE users SET is_admin = 0 WHERE is_admin IS NULL"))

    inspector = inspect(engine)
    final_columns = [column["name"] for column in inspector.get_columns("users")]

    missing = [column for column in REQUIRED_COLUMNS if column not in final_columns]

    if missing:
        raise RuntimeError(f"Migration failed. Missing columns: {missing}")

    print("Migration complete: v3.3 auth columns verified.")


if __name__ == "__main__":
    main()
