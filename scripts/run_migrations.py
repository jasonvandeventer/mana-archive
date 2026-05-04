from app.db import engine
from app.migrations import ensure_migrations_table, has_migration, record_migration
from scripts.migrate_v3_4_decks_as_locations import main as migrate_v3_4
from scripts.migrate_v3_5_drop_deck_items import main as migrate_v3_5_deck_items
from scripts.migrate_v3_5_inventory_role import main as migrate_v3_5_role
from scripts.migrate_v3_7_admin_user import main as migrate_v3_7_admin
from scripts.migrate_v3_8_8_color_identity import main as migrate_v3_8_8_color_identity
from scripts.migrate_v3_8_card_attrs import main as migrate_v3_8_card_attrs
from scripts.migrate_v3_9_5_row_tags import main as migrate_v3_9_5_row_tags


def _is_applied(name: str) -> bool:
    with engine.connect() as conn:
        return has_migration(conn, name)


def _mark_applied(name: str) -> None:
    with engine.begin() as conn:
        record_migration(conn, name)


def run():
    print("Starting migration runner")

    ensure_migrations_table()

    if not _is_applied("v3_4_decks_as_locations"):
        print("Running v3.4 migration...")
        migrate_v3_4()
        _mark_applied("v3_4_decks_as_locations")
    else:
        print("v3.4 migration already applied, skipping")

    if not _is_applied("v3_5_drop_deck_items"):
        print("Running v3.5 drop deck_items migration...")
        migrate_v3_5_deck_items()
        _mark_applied("v3_5_drop_deck_items")
    else:
        print("v3.5 drop_deck_items already applied, skipping")

    if not _is_applied("v3_5_inventory_role"):
        print("Running v3.5 inventory role migration...")
        migrate_v3_5_role()
        _mark_applied("v3_5_inventory_role")
    else:
        print("v3.5 inventory_role already applied, skipping")

    if not _is_applied("v3_7_admin_user"):
        print("Running v3.7 admin user migration...")
        migrate_v3_7_admin()
        _mark_applied("v3_7_admin_user")
    else:
        print("v3.7 admin_user already applied, skipping")

    if not _is_applied("v3_8_card_attrs"):
        print("Running v3.8 card attrs migration...")
        migrate_v3_8_card_attrs()
        _mark_applied("v3_8_card_attrs")
    else:
        print("v3.8 card_attrs already applied, skipping")

    if not _is_applied("v3_8_8_color_identity"):
        print("Running v3.8.8 color_identity migration...")
        migrate_v3_8_8_color_identity()
        _mark_applied("v3_8_8_color_identity")
    else:
        print("v3.8.8 color_identity already applied, skipping")

    if not _is_applied("v3_9_5_row_tags"):
        print("Running v3.9.5 row tags migration...")
        migrate_v3_9_5_row_tags()
        _mark_applied("v3_9_5_row_tags")
    else:
        print("v3.9.5 row_tags already applied, skipping")

    print("Migration runner complete")


if __name__ == "__main__":
    run()
