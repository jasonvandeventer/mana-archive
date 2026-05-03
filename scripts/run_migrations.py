from app.db import engine
from app.migrations import ensure_migrations_table, has_migration, record_migration
from scripts.migrate_v3_4_decks_as_locations import main as migrate_v3_4
from scripts.migrate_v3_5_drop_deck_items import main as migrate_v3_5_deck_items
from scripts.migrate_v3_5_inventory_role import main as migrate_v3_5_role


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

        if not has_migration(conn, "v3_5_drop_deck_items"):
            print("Running v3.5 drop deck_items migration...")
            migrate_v3_5_deck_items()
            record_migration(conn, "v3_5_drop_deck_items")
        else:
            print("v3.5 drop_deck_items already applied, skipping")

        if not has_migration(conn, "v3_5_inventory_role"):
            print("Running v3.5 inventory role migration...")
            migrate_v3_5_role()
            record_migration(conn, "v3_5_inventory_role")
        else:
            print("v3.5 inventory_role already applied, skipping")

    print("Migration runner complete")


if __name__ == "__main__":
    run()
