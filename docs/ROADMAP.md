# Mana Archive Roadmap

Mana Archive is primarily a personal collection-management app. The roadmap should keep that priority clear while still leaving room for trusted playgroup use, collector workflows, and future gameplay tools.

## Current Product Direction

Primary goals:

1. Make Mana Archive more useful for managing my own collection.
2. Add deck management, because that is the largest current personal usability gap.
3. Let one trusted collector/playgroup member use the app without seeing or modifying my data.
4. Improve card intake only after multi-user access creates a real onboarding need.
5. Continue alternating Mana Archive feature work with K3s platform, documentation, and career polish.

Mana Archive should not become public-SaaS-shaped too early. The near-term target is a reliable private tool for one primary user and a small number of trusted playgroup users.

---

## Roadmap Triage Rules

New bugs and feature ideas should be classified before implementation:

- **Blocking bug:** fix immediately if it affects data integrity, imports, login/session behavior, deployment, backups, or normal collection use.
- **Same-sprint improvement:** implement only if it directly supports the current release goal.
- **Roadmap item:** capture it under the appropriate future version and keep moving.
- **Interesting distraction:** do not implement unless it repeatedly becomes a real pain point.

Current priority order:

1. Stabilize collection, Sets, and pending relocation workflows.
2. Add deck management for personal usability.
3. Add private multi-user support and flexible storage for trusted playgroup use.
4. Improve collection intake/import workflows.
5. Expand collector, scanner, deck, gameplay, and intelligence features over time.

---

## v2.1.x — Collection + Sets Stabilization

**Theme:** finish the current collection-management loop before expanding the product.

### Core Features

- Enhanced Pending view
  - Show previous location → new location.
  - Use `TransactionLog` as the source of movement history.
  - Make physical relocation unambiguous.
- Drawer Sorter improvements
  - Cards that move between drawers should surface in Pending.
  - Pending should make it clear which physical cards must be moved and validated.
- Sets page stabilization
  - Set list/dashboard entry point.
  - Individual set view.
  - Owned vs missing counts.
  - Completion percentage.
  - Missing cards sorted by collector number.
  - Scryfall set-card cache performance improvements.
- Import/batch bugfixes
- Dashboard updates for Sets
- General performance cleanup

### Acceptance Criteria

- Existing single-user collection workflows remain stable.
- Pending makes physical moves obvious.
- Sets pages load reliably without obvious first-load timeout pain.
- The dashboard reflects the current collection and Sets features.

### Notes

This version line is still about making the existing app coherent, fast, and trustworthy.

---

## v2.2.0-beta.1 — Deck Management Foundation

**Theme:** make Mana Archive useful for building and tracking Commander decks.

Deck management is the highest-priority personal usability gap. This should come before broader playgroup features unless another user needs access immediately.

### Core Features

- Deck list page
- Deck detail page
- Create/edit/delete decks
- Assign commander
- Add cards to a deck
- Track card quantities
- Track deck card count
- Show owned vs missing cards
- Show physical location for owned cards when possible
- Basic Commander deck size validation
- Deck notes

### Suggested Schema

```text
Deck
- id
- name
- commander_name
- description
- notes
- created_at
- updated_at

DeckCard
- id
- deck_id
- card_name
- scryfall_id
- quantity
- role
- owned_card_id nullable
```

### Suggested Card Roles

- ramp
- draw
- removal
- board wipe
- land
- protection
- win condition
- utility
- other

### Acceptance Criteria

- I can create a Commander deck.
- I can add cards to that deck.
- I can see what I own.
- I can see what I am missing.
- I can use the app while physically assembling or tuning a deck.

---

## v2.2.0-beta.2 — Deck Management Hardening

**Theme:** make decks pleasant enough to use repeatedly.

### Core Features

- Better deck card editing
- Add/remove/update quantities from the deck detail page
- Move cards between roles/sections
- Deck summary stats
- Land/nonland count
- Basic mana value curve
- Color identity display
- Missing-card report
- Collection lookup from deck view
- Better empty states

### Acceptance Criteria

- Deck pages answer practical questions quickly:
  - Do I own this card?
  - Where is it?
  - What am I missing?
  - What role does this card play in the deck?

---

## v2.2.0 — Stable Deck Management Release

**Theme:** Mana Archive becomes both a collection tracker and a deck-management tool.

### Core Features

- Stable deck CRUD
- Stable collection-to-deck relationship
- Stable missing-card report
- Basic deck stats
- Updated documentation

### Acceptance Criteria

- Mana Archive can manage my collection and help me assemble decks from it.

---

## v2.3.0-beta.1 — Private Multi-User Data Isolation

**Theme:** allow one trusted collector/playgroup member to use the app without touching my data.

This is not public SaaS multi-tenancy. This is trusted small-group account isolation.

### Core Features

- Manual user creation
- Login/logout
- Password hashing
- Session-based current user
- Existing collection assigned to the default/Jason user
- New users start with empty collections
- `user_id` added to collection/inventory records
- `user_id` added to deck records if deck management already exists
- `user_id` added to storage records if storage exists at this point
- Collection queries filtered by current user
- Deck queries filtered by current user
- Storage queries filtered by current user
- Sets page works from the current user’s collection data

### Acceptance Criteria

- Jason logs in and sees Jason’s collection.
- The collector friend logs in and sees an empty personal collection.
- The collector friend can use Sets without seeing Jason’s data.
- No user can modify another user’s cards, decks, or storage data through normal app workflows.

---

## v2.3.0-beta.2 — Flexible Storage Per User

**Theme:** let each user model their real physical storage instead of assuming Jason’s drawer setup.

### Core Features

- `storage_locations` table
- Storage Settings page
- User-owned storage locations
- Cards assigned to storage locations
- Replace drawer-only assumptions in UI copy and queries
- Keep Jason’s card catalog/drawer model working
- Let other users define binders, boxes, shelves, deck boxes, or other storage systems

### Suggested Schema

```text
StorageLocation
- id
- user_id
- name
- type
- description
- sort_order
- is_active
- created_at
- updated_at
```

### Suggested Storage Types

- drawer
- binder
- box
- deck box
- shelf
- bulk storage
- other

### Acceptance Criteria

- Jason can keep using Drawer 1, Drawer 2, etc.
- Another user can create Binder 1, Trade Box, Bulk Box, or similar.
- Collection views show each user’s own storage names.
- No user sees another user’s storage locations.

---

## v2.3.0 — Stable Private Multi-User + Flexible Storage Release

**Theme:** Mana Archive safely supports Jason plus a trusted collector/playgroup user.

### Core Features

- Stable login/logout
- Stable per-user data separation
- Stable per-user storage locations
- Sets page works per user
- Decks work per user if deck management already exists
- Basic account creation process documented
- Backup-before-upgrade note documented

### Acceptance Criteria

- Mana Archive can support my own workflow and one collector friend’s workflow without data leakage or data corruption.

---

## v2.4.0-beta.1 — Fast Collection Intake

**Theme:** make it less painful for another user to add cards.

This becomes important after another user has access. Manual entry is acceptable for testing a few cards, but not for real adoption.

### Core Features

- Bulk paste import
- Plain text card-list parser
- Quantity parsing
- Scryfall-assisted card matching
- Import review screen
- Storage location selection during import
- Imported cards assigned to current user

### Example Input

```text
1 Sol Ring
1 Arcane Signet
1 Swords to Plowshares
1 Counterspell
```

### Acceptance Criteria

- A user can add 50–100 cards without manually searching and submitting each card one by one.
- The user can review matches before the collection is changed.

---

## v2.4.0-beta.2 — Import Cleanup + Duplicate Handling

**Theme:** make imports trustworthy.

### Core Features

- Duplicate detection
- Quantity updates for existing owned cards
- Unmatched-card review
- Import error report
- Exact-printing fallback
- Optional set code / collector number support
- Large import progress feedback

### Acceptance Criteria

- Users can tell what was added, skipped, matched, or needs correction.
- Imports do not silently create confusing duplicate data.

---

## v2.4.0 — Stable Fast Intake Release

**Theme:** onboarding becomes realistic.

### Core Features

- Stable bulk import
- Stable review screen
- Storage assignment during import
- Import documentation

### Acceptance Criteria

- A trusted user can begin adding real collection data without hating the process.

---

## v2.5.0-beta.1 — Set Collector Improvements

**Theme:** deepen the collector workflow that started with Sets.

### Core Features

- Set completion percentage
- Missing cards by set
- Owned cards by set
- Filter by rarity
- Filter by color/type
- Set checklist view
- Wishlist/missing list
- Export missing cards

### Acceptance Criteria

- A collector can answer: “What am I missing from this set?”

---

## v2.5.0-beta.2 — Collector Workflow Polish

**Theme:** make set tracking actionable.

### Core Features

- Mark cards as wanted
- Priority wishlist
- Trade/sell candidate flag
- Duplicate count visibility
- Foil/nonfoil distinction if needed
- Collector-number-focused view

### Acceptance Criteria

- A collector can use Mana Archive to guide purchases, trades, and sorting.

---

## v2.5.0 — Stable Collector Release

**Theme:** Mana Archive supports both deckbuilding and collector workflows.

### Core Features

- Stable set completion tracking
- Stable missing-card tracking
- Stable wishlist/missing export
- Documentation updated

### Acceptance Criteria

- Mana Archive supports my primary deckbuilding/storage workflow and my collector friend’s set-completion workflow.

---

## v2.6.0-beta.1 — Camera-Assisted Scanner Prototype

**Theme:** speed up physical card entry.

Scanner work should happen after the data model and import flow are stable. The scanner should suggest; the user should confirm.

### Core Features

- Browser camera page
- Capture image
- OCR card-name extraction
- Scryfall lookup
- User confirms match before add
- Storage location selection
- Mobile/tablet-friendly scan UI

### Acceptance Criteria

- A user can scan a card, confirm the likely match, and add it to their collection.
- Scanner output does not directly mutate collection data without confirmation.

---

## v2.7.0-beta.1 — Deck Import / Export

**Theme:** connect Mana Archive to existing deckbuilding tools.

### Core Features

- Import decklists
- Export decklists
- Moxfield-compatible text export
- Archidekt-compatible text export
- Missing-card report from imported deck
- Maybe-board support

### Acceptance Criteria

- I can move decklists between Mana Archive and common deckbuilding tools without retyping everything.

---

## v2.8.0-beta.1 — Commander Life Tracker

**Theme:** add useful table-side gameplay tools.

This should be a web/PWA-style feature inside Mana Archive, not a native Linux app unless desktop app development becomes a separate goal.

### Core Features

- 4-player Commander layout
- Life totals
- Poison counters
- Commander damage
- Player names
- Reset game
- Local browser persistence
- Touch-friendly layout

### Acceptance Criteria

- The playgroup can use Mana Archive as a simple Commander table tool.

---

## v2.9.0-beta.1 — Game History + Deck Performance

**Theme:** connect gameplay back to deck management.

### Core Features

- Select deck for player
- Save game result
- Track wins/losses
- Track commander used
- Game notes
- Basic deck performance stats

### Acceptance Criteria

- Mana Archive can show which decks are being played and how they perform.

---

## v3.0.0 — Private Playgroup Product Milestone

**Theme:** Mana Archive becomes a coherent private MTG utility for collection, decks, collectors, and gameplay.

Potential stable bundle:

- Collection tracking
- Sets tracking
- Deck management
- Multi-user isolation
- Flexible storage
- Fast intake/imports
- Collector workflows
- Scanner-assisted intake
- Basic gameplay utilities
- Game history/deck performance

### Acceptance Criteria

- Mana Archive is no longer just a personal card catalog. It is a useful private playgroup MTG tool while still primarily serving my own collection workflow.

---

## Future / Maybe

These are useful ideas, but they should not interrupt the core roadmap.

### Collection Intelligence

- Duplicate detection
- Excess-copy reporting
- Trade/sell candidates
- Total collection value
- Value by storage location
- Value by set
- Top valuable cards
- Near-complete set suggestions
- Low-cost missing-card suggestions

### Operational Maturity Inside the App

- Audit log UI
- Filter movement history by card, storage location, or event type
- Bulk confirm pending
- Bulk move/delete
- Drawer/storage audit mode
- Backup/restore UX if appropriate

### Public/Product Features

- Public collection view
- Shareable deck pages
- Shareable collection pages
- Public playgroup pages
- OAuth/OIDC login
- Invite links
- Role-based permissions

These should wait until there is a real need. Manual accounts and trusted-user workflows are enough for the near future.

---

## Alternating Mana Archive Work With Platform Work

Mana Archive should remain fun, but it should also continue strengthening the larger platform story.

Suggested rhythm:

```text
Mana Archive feature sprint
Platform polish sprint
Mana Archive feature sprint
Documentation/storytelling sprint
Mana Archive feature sprint
Platform observability/security sprint
```

Practical near-term example:

```text
Mana Archive v2.1.x stabilization
→ Platform observability: Prometheus / Grafana / Loki
→ Mana Archive v2.2.x deck management
→ Career docs: architecture README, screenshots, demo story
→ Mana Archive v2.3.x multi-user + flexible storage
→ Platform security polish: scanning, secrets, runbooks
```

---

## Guiding Principles

- Data integrity beats feature count.
- The physical collection is the source of truth.
- Every feature should improve clarity, correctness, or usability.
- Deck management is the next major personal usability win.
- Multi-user support exists to support trusted users, not to prematurely become SaaS.
- Scanner features should assist the user, not silently mutate collection data.
- Public/product features should wait until the private workflow is genuinely strong.
