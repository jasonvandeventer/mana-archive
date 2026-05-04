# Mana Archive — Claude Context

## Current version: v3.8.0

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

All import paths (CSV, paste list, and manual) present a **Destination** dropdown at commit time. For drawer-sorter users the first option is "Auto-sort to drawers" (existing behaviour); any other selection places cards directly into that StorageLocation and skips pending entirely. For other users, a location must be chosen.

**Decks appear as destinations** in the dropdown (as a separate `<optgroup>`), using the deck's `storage_location_id` as the value. This lets users import directly into a deck without the placement step. `place_imported_rows()` in `inventory_service.py` handles bulk placement to any location, including deck locations.

The `decks` list (from `list_decks()`) is passed to all three preview templates: `import_preview.html`, `manual_preview.html`.

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

Idempotent migration scripts live in `scripts/`. `scripts/run_migrations.py` is the runner — add new migrations there in order. Each migration is tracked by name in the `schema_migrations` SQLite table. `run_migrations()` is called from `on_startup()` in `main.py`, so every deploy automatically applies pending migrations before the app serves traffic.

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

### Import format support (v3.6)

Two import paths on `/import`:

**CSV upload** — `parse_scanner_csv()` auto-detects format from column headers:

- **Scanner App** (default): `scryfall_id / set_code / collector_number / finish / quantity`
- **Helvault** (free & pro): detected by `extras` column (→ `finish`). Resolved via Scryfall ID.
- **Moxfield** collection CSV: detected by `Edition` column. Maps `Edition → set_code`, `Foil → finish`, `Count → quantity`. Resolved via set+collector number.

**Paste card list** — `parse_text_list()` parses `N CardName (SET) Collector#` format:

- Accepts Moxfield deck exports, MTGA, MTGO, and any standard text list format.
- Lookup priority: set+collector → exact name+set → fuzzy name.
- `fetch_card_by_name()` in `scryfall.py` handles exact then fuzzy Scryfall `/cards/named` lookups.
- Section headers (Deck, Sideboard, Commander, etc.) are silently skipped.
- MTGA foil marker (`*F*`) is detected and mapped to finish=foil.

Both paths normalize to the same row dict and feed into `persist_import_rows()` via the shared preview → commit flow. `format_name` is shown on the preview page.

### UI/UX consistency (v3.7)

All templates use a consistent panel/section structure:

- Hero sections: `class="panel page-hero"` (large) or `class="panel hero-panel compact-hero"` (compact)
- Action/filter strips: `class="panel controls-panel"` (block layout; form inside uses `.filter-row` for flex)
- Content panels: `class="panel"` with `<h3 class="panel-title">` inside
- Tables: globally styled — no extra class needed, just bare `<table>`
- CSS utilities in `style.css`: `.controls-panel`, `.btn-danger-small`, `.finish-badge`, `.warning-text`

Templates updated in v3.7: `decks.html`, `import.html`, `import_preview.html`, `manual_preview.html`, `audit.html`, `sets.html`, `set_detail.html`, `pending.html`, `locations.html`, `drawers.html`, `card_detail.html`, `login.html`, `register.html`, `manual_search_results.html`, `import_result.html`.

### Admin and account (v3.7)

- `GET /admin` — admin-only page (gated by `User.is_admin`). Shows all users with card count, deck count, last activity. Actions: toggle active/inactive, toggle admin, reset password, create new user, delete user (cascade-deletes all their data).
- `GET /account` + `POST /account/change-password` — available to all authenticated users; password change requires current password verification.
- `require_admin` dependency in `app/dependencies.py` — raises 403 if `current_user.is_admin` is false.
- Admin/Account links appear in nav. Admin link is gated by `current_user.is_admin`.
- Migration `v3_7_admin_user` ensures `users.is_admin` column exists and seeds `jason.v` as admin.
- Delete user cascade order: TransactionLog → InventoryRow → ImportBatch → Deck → StorageLocation → User.

### Card attributes (v3.8)

- `Card` model gains `colors` (space-sep WUBRG, e.g. `"W U"`), `mana_cost` (e.g. `"{2}{W}"`), `cmc` (float). Migration `v3_8_card_attrs` adds columns; background price-refresh loop backfills existing cards as they age past 7 days.
- Extended search syntax everywhere: `c:WU`, `cmc:>3`, `mana:{W}`, on top of existing `t:`, `o:`, `s:`, `r:`, `finish:`.
- New sort options on collection and location detail: Type, Color (WUBRG order), Mana Cost.
- Location detail now has search + sort controls (previously unsorted, no search).
- Deck detail search upgraded from plain substring to full Scryfall-style syntax.
- Unified card display via `_macros.html` `inventory_card` macro — collection, location detail, deck detail all render from one place.
- Import resort is now a background daemon thread (non-blocking); explicit "Apply Drawer Sorter" stays synchronous.
- Pre-commit hook at `.githooks/pre-commit` mirrors CI lint checks. New developers run `git config core.hooksPath .githooks`.
- Token tracking on set detail: "Show Tokens" toggle fetches `t{set_code}` token set; tokens tracked ownership-only (no USD price).

## Roadmap

- v3.7: Import-to-deck, decks list redesign, full UI/UX consistency pass, admin CRUD, account page — **shipped**
- v3.8: Card attrs (colors/cmc/mana_cost), async resort, extended search, unified card macro, token tracking, pre-commit hook — **shipped**
- v3.9: Legality sort/filter (needs schema design), advanced deck analytics
- v4.0: PostgreSQL migration
