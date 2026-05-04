# Mana Archive — Claude Context

## Current version: v3.8.9-1

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

- `Card` model gains `colors` (space-sep WUBRG, e.g. `"W U"`), `color_identity` (space-sep WUBRG, `""` = colorless — distinct from `colors` for cards with colored abilities/land types), `mana_cost` (e.g. `"{2}{W}"`), `cmc` (float). Migration `v3_8_card_attrs` adds colors/mana_cost/cmc; migration `v3_8_8_color_identity` adds color_identity. Refresh loop backfills cards with NULL `color_identity`.
- Extended search syntax everywhere: `c:WU`, `cmc:>3`, `mana:{W}`, on top of existing `t:`, `o:`, `s:`, `r:`, `finish:`.
- New sort options on collection and location detail: Type, Color (WUBRG order), Mana Cost.
- Location detail now has search + sort controls (previously unsorted, no search).
- Deck detail search upgraded from plain substring to full Scryfall-style syntax.
- Unified card display via `_macros.html` `inventory_card` macro — collection, location detail, deck detail all render from one place.
- Import resort is now a background daemon thread (non-blocking); explicit "Apply Drawer Sorter" stays synchronous.
- Pre-commit hook at `.githooks/pre-commit` mirrors CI lint checks. New developers run `git config core.hooksPath .githooks`.
- Token tracking on set detail: "Show Tokens" toggle fetches `t{set_code}` token set; tokens tracked ownership-only (no USD price).

### Deck analytics (v3.8.4)

- `compute_deck_analytics(rows)` in `deck_service.py` — takes a list of unfiltered `InventoryRow` ORM objects and returns mana curve (bucketed 0–6+, lands excluded), card type breakdown (Creature → Planeswalker → Battle → Instant → Sorcery → Enchantment → Artifact → Land → Other), color pip counts (parsed from `mana_cost`), and average CMC.
- `compute_deck_tokens(rows)` in `deck_service.py` — returns deduplicated list of `{name, type_line, image_url, set_code, collector_number, scryfall_id}` dicts for tokens produceable by the deck. Calls `fetch_deck_tokens()` in `scryfall.py`: Pass 1 batch-fetches deck cards to collect token stubs from `all_parts` (component="token"); Pass 2 batch-fetches the token cards themselves for `image_uris` and set info. Cached per unique card set keyed on `(_DECK_TOKEN_CACHE_VERSION, frozenset)` — bump version when dict shape changes.
- `deck_detail_page` in `main.py` always runs a separate unfiltered query for analytics so the panel reflects the full deck even when the search filter is active. Analytics are `None` for empty decks.
- Analytics panel in `deck_detail.html` — 3-column layout: Mana Curve | Card Types | Color Pips. Avg CMC shown as a prominent stat. Collapses to 2-col when no pips, stacks on mobile. Vertical dividers between columns.
- Tokens panel in `deck_detail.html` — separate panel below the deck card grid. Responsive image grid (`token-image-grid`); clicking a token image opens `/tokens/{scryfall_id}` (internal detail page); clicking the name opens Scryfall in a new tab.
- `GET /tokens/{scryfall_id}` — token detail page using `token_detail.html`. Fetches token data via `fetch_card_by_scryfall_id` (cached). Shows large image, type line, oracle text, Scryfall link. No inventory section (tokens not owned).
- Remove-from-deck override fields (drawer/slot) collapsed into a `<details class="return-details">` — "Remove from Deck" summary expands to reveal override inputs + "Confirm Remove" submit. Only shown for drawer-sorter users on non-commander rows.
- CSS: `.analytics-grid`, `.analytics-section`, `.analytics-avg-cmc`, `.analytics-curve`, `.curve-col/.curve-bar/.curve-count/.curve-label`, `.analytics-row`, `.arow-label/.arow-bar-wrap/.arow-bar/.arow-count`, WUBRG gradient bars, `.token-image-grid/.token-card/.token-card-img/.token-card-placeholder/.token-card-name/.token-card-type`, `.return-details/.return-summary`.

### Brand assets and header layout (v3.8.3)

- `app/static/icons/` — actual brand PNGs at 15 sizes (16–1024px) using card-frame app icon design; wordmark PNGs at 256/512/1024px; `favicon.ico` built from 16/32/48px icons.
- `base.html` favicon chain: `favicon.ico` (legacy) → `icon-32x32.png` (PNG fallback) → `icon-180x180.png` (Apple touch icon).
- Header restructured to two-column flex layout: left column = wordmark + nav stacked; right column = version pill + logout stacked. This aligns logout with the nav row at the far right.
- Brand area uses `wordmark-1024.png` displayed at 44px height (`class="brand-wordmark"`) — no separate icon + text elements.
- CSS classes: `.header-left` (flex-column, space-between), `.brand-wordmark` (height 44px, auto width). Removed `.brand-row`, `.brand-icon`, `.brand-text`.
- `list_decks()` in `deck_service.py` now sums `InventoryRow.quantity` (total copies) for `card_count` instead of counting distinct rows.

### Location page deck management (v3.8.2)

- `POST /locations/create-deck` — creates a proper `Deck` record + linked `StorageLocation` from the Locations page; redirects back to `/locations`. Form has name + format dropdown (same options as Decks page).
- Orphaned deck locations (type="deck", no linked `Deck` record, no rows) now show a Delete button in the Locations table. `delete_location()` allows deletion when no `Deck` references the location; blocks with a clear error if a live `Deck` still owns it.
- `get_location_summary()` computes `is_deletable` per location (used by template to show/hide Delete); avoids duplicating the logic in the template.

### Deck/location UX fixes (v3.8.1)

- `GET /locations/{id}` redirects to `/decks/{deck_id}` when `location.type == "deck"` — eliminates duplicate access path.
- Deck detail gains sort controls (Name, Type, Mana Cost, Price) matching location detail.
- Import destination dropdowns (`import_preview.html`, `manual_preview.html`) exclude `type="deck"` locations from the Storage Locations optgroup — deck locations only appear under the Decks optgroup.
- `delete_location()` in `location_service.py` + `POST /locations/{id}/delete` route — deletes empty non-root, non-deck locations. Delete button appears in locations table only when `row_count == 0`.
- `location_types` in create form excludes "deck" — prevents creating orphaned deck-type StorageLocations not linked to a Deck record.
- Collection card actions collapsed into a `<details class="card-actions-drawer">` — cards show only info by default; "Actions ▾" expands Remove, Add to Deck, Move, and Sell/Trade/Delete/Refresh inline.
- Fixed deck card tile overflow: deck actions section now uses `flex-direction: column`; removed misapplied `compact-form-grid` class from return form.

### Boolean search logic (v3.8.5)

- `apply_collection_search_filters()` in `inventory_service.py` now parses full Scryfall-style boolean logic. Public signature unchanged — all three search surfaces (collection, location detail, deck detail) get the upgrade for free.
- **Operators**: `OR` (explicit), `AND` (explicit or implicit between adjacent terms), `-` prefix for negation (e.g. `-t:land`, `-folio`).
- **Grouping**: parentheses `(t:creature OR t:planeswalker)` for complex expressions.
- **Quoted multi-word values**: `t:"legendary creature"`, `o:"draw a card"`, `"lightning bolt"`.
- Implementation: `_tokenize_search()` → flat token list; `_term_to_clause()` → single SQLAlchemy clause; `_parse_search_expr()` / `_parse_and_expr()` / `_parse_atom()` → recursive-descent parser building nested `and_()` / `or_()` / `not_()` clauses.
- Malformed queries fall back to no-filter rather than 500.

### Search polish (v3.8.6)

- `OR` / `AND` keywords are now case-insensitive (`or`, `Or`, `OR` all work).
- `not:X` is syntactic sugar for `-is:X` (double-negation via `-not:X` cancels correctly).
- New keywords in `_term_to_clause()`:
  - `is:foil` / `is:nonfoil` / `is:etched` — finish filter; `not:foil` inverts
  - `is:commander` — cards flagged as commander in a deck
  - `n:` / `name:` — explicit name prefix (same as bare word, useful in complex expressions)
  - `qty:`/`q:`/`quantity:` — numeric quantity filter (e.g. `qty:>1` to find duplicates)
  - `price:`/`usd:` — numeric price filter against `Card.price_usd` cast to float (e.g. `price:>=5`)
- `id:` color identity filter: "within" subset check — excludes cards containing any color not in the given set. Uses `Card.color_identity` (exact Scryfall field, added v3.8.8); cards with `NULL` identity are excluded until backfilled.
- Placeholder text in all three search inputs updated to show real example queries with boolean syntax.

## Deployment and versioning

- CI builds and pushes to GHCR on any tag matching `v*.*.*`. Untagged commits run lint only.
- ArgoCD Image Updater (semver strategy) watches GHCR and writes the new tag to `.argocd-source-mana-archive.yaml` in `mana-archive-platform`, which ArgoCD then syncs to the cluster.
- **Version convention**: always bump the patch number — never use `-N` suffixes. `v3.8.9` → hotfix → `v3.8.10`. Semver treats `-N` as a pre-release (sorts *below* the base tag) so the Image Updater ignores it.
- **Tagging is automatic**: the `.githooks/post-commit` hook tags HEAD whenever the commit message starts with `vX.Y.Z:`. No separate `git tag` step needed.
- New developers must run `git config core.hooksPath .githooks` to activate both the pre-commit lint check and the post-commit auto-tag.

## Roadmap

- v3.7: Import-to-deck, decks list redesign, full UI/UX consistency pass, admin CRUD, account page — **shipped**
- v3.8: Card attrs (colors/cmc/mana_cost), async resort, extended search, unified card macro, token tracking, pre-commit hook — **shipped**
- v3.8.1: Deck/location UX fixes, collection action drawer — **shipped**
- v3.8.2: Location page deck creation, orphaned deck location cleanup — **shipped**
- v3.8.3: Brand assets (real PNG icon pack + wordmark), header two-column layout, deck total-copy count — **shipped**
- v3.8.4: Deck analytics panel (mana curve, card types, color pips, avg CMC) — **shipped**
- v3.8.5: Boolean search logic (OR, AND, NOT/-, parentheses, quoted multi-word values) — **shipped**
- v3.8.6: Search polish — case-insensitive OR/AND, not: keyword, is:/qty:/price:/name: keywords, updated placeholders — **shipped**
- v3.8.7: id: color identity filter bug fixes — NULL colors excluded by SQLite NOT LIKE; refresh loop now also picks up cards with NULL colors; one-time backfill via individual + set/collector Scryfall fallback fixed ~1,400 stale scryfall_ids — **shipped**
- v3.8.8: `color_identity` column on `Card` — proper Scryfall `color_identity` field (space-sep WUBRG, `""` = colorless, `NULL` = not yet fetched); `id:` filter now uses this instead of approximating from `colors`; migration `v3_8_8_color_identity` adds column; refresh loop and all card-write paths updated — **shipped**
- v3.8.9: Deck token panel (image grid, `/tokens/{scryfall_id}` detail page), collapse remove-from-deck overrides into `<details>`, post-commit auto-tag hook — **shipped**
- v3.9: Legality sort/filter (needs schema design), game tracker (life totals, 2–8 players, deck selection per seat, results tied to deck records)
- v4.0: PostgreSQL migration
