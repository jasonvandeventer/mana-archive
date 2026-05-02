from app.db import engine
from app.migrations import ensure_migrations_table, has_migration, record_migration
from scripts.migrate_v3_4_decks_as_locations import main as migrate_v3_4


def run():
    print("Starting migration runner")

    ensure_migrations_table()

    with engine.begin() as conn:
        if not has_migration(conn, "v3_4_decks_as_locations"):
            print("Running v3.4 migration...")
            migrate_v3_4()
            record_migration(conn, "v3_4_decks_as_locations")
        else:
            print("v3.4 migration already applied, skipping")

    print("Migration runner complete")


if __name__ == "__main__":
    run()
