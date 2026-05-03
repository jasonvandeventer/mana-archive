# Mana Archive — Claude Context

## Current version: v3.5.0

## Stack: FastAPI + Jinja2 + SQLite + K3s/ArgoCD

## Non-negotiable constraints

- InventoryRow is the single source of truth
- StorageLocation is the canonical location system (decks = type="deck")
- SQLite until v4 — do NOT suggest PostgreSQL changes
- No service layers unless already present
- Do NOT break existing routes or templates (live system)

## Current phase

Active user onboarding. Multi-user support now in place — hardening usability for non-admin users.

## Architecture notes

### Drawer sorter

`DRAWER_SORTER_USERNAMES = frozenset({"jason.v", "test"})` in `app/dependencies.py` gates the automatic 6-drawer card sorter (`resort_collection`). Only these users get drawer/slot auto-assignment on import and access to the Drawers page, Audit page, and "Apply Drawer Sorter" button.

All other users manage their own StorageLocations and pick placement manually.

To add a user to the auto-sorter, update `DRAWER_SORTER_USERNAMES` in `app/dependencies.py` (one place — it's injected as a Jinja2 global and imported into `main.py`).

### Import destination

All import paths (CSV and manual) present a **Destination** dropdown at commit time. For drawer-sorter users the first option is "Auto-sort to drawers" (existing behaviour); any other selection places cards directly into that StorageLocation and skips pending entirely. For other users, a location must be chosen. `place_imported_rows()` in `inventory_service.py` handles the bulk placement.

### Security (added v3.4.6)

- CSRF protection: session token via `CsrfRequired` dependency on all POST routes; `{{ csrf_token }}` hidden field in every form
- Open redirect prevention: `safe_redirect_url()` in `main.py` validates Referer before redirect
- ValueError handler: returns clean 400 instead of 500 stack trace
- Session secret: startup check refuses to boot in production without `SESSION_SECRET_KEY` env var

### Shared rendering

`render()`, `CsrfRequired`, `get_csrf_token()`, and `get_current_user()` all live in `app/dependencies.py`. Do not redefine them elsewhere.

### StorageLocation auto-creation

`_get_or_create_drawer_location()` in `inventory_service.py` bootstraps missing drawer StorageLocations on first confirm. Prevents 500s for users whose drawer rows don't exist yet.

### DeckItem removed (v3.5)

`DeckItem` model and `deck_items` table are gone. Deck cards have always been `InventoryRow` records with `storage_location_id` pointing to the deck's StorageLocation — DeckItem was dead code after the v3.4 migration. The drop is in `scripts/migrate_v3_5_drop_deck_items.py`.

### Commander role (v3.5)

`InventoryRow.role` (nullable String(32)) marks a card's role within a deck. Currently only value used is `"commander"`. Set via `POST /decks/rows/{row_id}/toggle-commander`. In `deck_detail.html`, cards with `role=="commander"` appear in a separate **Commander(s)** panel above the main deck grid. Added via `scripts/migrate_v3_5_inventory_role.py`.

### Migrations

Idempotent migration scripts live in `scripts/`. `scripts/run_migrations.py` is the runner — add new migrations there in order. Each migration is tracked by name in the `schema_migrations` SQLite table.

## Telemetry query

kubectl exec -n mana-archive deploy/mana-archive -- \
python -c "from sqlalchemy import text; from app.db import engine; \
conn = engine.connect(); \
rows = conn.execute(text('''
SELECT u.username,
COUNT(DISTINCT ir.id) as inventory_rows,
COUNT(DISTINCT d.id) as decks
FROM users u
LEFT JOIN inventory_rows ir ON u.id = ir.user_id
LEFT JOIN decks d ON u.id = d.user_id
GROUP BY u.username
ORDER BY inventory_rows DESC
''')).fetchall(); \
print('\n'.join(str(r) for r in rows)); conn.close()"

## Roadmap

- v3.6: Import framework (Helvault, Moxfield CSV)
- v4.0: PostgreSQL migration
