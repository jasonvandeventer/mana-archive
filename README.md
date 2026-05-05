![Mana Archive](app/static/icons/wordmark-512.png)

Self-hosted web application for managing a physical Magic: The Gathering collection.

**Current version: v3.11.18** · [Platform repo](https://github.com/jasonvandeventer/mana-archive-platform)

---

## Features

### Collection

- Browse and search your full inventory with Scryfall-style boolean syntax
- Keywords: `t:creature`, `c:WU`, `cmc:>3`, `o:"draw a card"`, `id:gb`, `price:>=5`, `is:foil`, `qty:>1`, and more
- Full boolean logic: `OR`, `AND`, `-negation`, `(grouping)`, quoted multi-word values
- Sort by name, type, mana cost, color, or price

### Imports

- **CSV upload** — auto-detects Scanner App, Helvault (free/pro), and Moxfield collection CSV formats
- **Paste list** — parses Moxfield deck exports, MTGA, MTGO, and standard `N CardName (SET) #` format
- Import directly to a deck or storage location at commit time

### Decks

- Create and manage Commander (or any format) decks; edit name, format, and notes inline
- Mark commanders; commander cards appear in a dedicated panel above the deck grid
- Full Scryfall-style search within a deck
- **Analytics panel**: mana curve, card type breakdown, color pip counts, avg CMC
- **Health panel**: ramp/draw/removal/board-wipe density vs recommended thresholds; pip strain analysis (colored pip demand vs land color sources)
- **Token panel**: auto-discovers tokens produceable by the deck via Scryfall `all_parts`; click a token image to view its detail page
- Click any health metric count to filter the deck grid to just those cards

### Organization

- Drawer/slot system for physical organization (gated per-user)
- Custom storage locations: create, edit (name/type/parent/sort order), and delete
- Move cards between locations from the location detail page or deck detail page
- **Bulk move**: select multiple cards from a location or deck and move them in one action; destination picker includes both storage locations and other decks
- Return cards from decks to pending/collection
- **CSV export**: download your full collection or any individual location as a CSV (Name, Set, Collector Number, Finish, Quantity, Location)

### Pricing & Card Data

- Live Scryfall pricing (USD regular, foil, etched) per card and deck totals
- Background price refresh loop keeps data fresh
- Card attributes: colors, color identity, mana cost, CMC, oracle text, type line

### Multi-user

- **Self-service registration** — users sign up with email + display name; no admin involvement required
- Admin panel: create/delete users, toggle admin/active, reset passwords
- Display names shown throughout the UI; email used as login identifier
- Per-user data isolation; drawer sorter is opt-in per username

### Sets

- Browse cards by set; token tracking toggle per set

---

## Stack

| Layer         | Technology                                    |
| ------------- | --------------------------------------------- |
| Web framework | FastAPI + Jinja2                              |
| Database      | SQLite (via SQLAlchemy)                       |
| Styling       | Custom CSS (no framework)                     |
| Card data     | [Scryfall API](https://scryfall.com/docs/api) |
| Runtime       | Docker / Kubernetes (K3s)                     |
| GitOps        | ArgoCD + ArgoCD Image Updater                 |

---

## Architecture

This repo contains **application code only**. Platform/infrastructure lives separately:

- **App repo** — this repo (FastAPI app, templates, migrations)
- **Platform repo** — [mana-archive-platform](https://github.com/jasonvandeventer/mana-archive-platform) (Kubernetes manifests, ArgoCD config)

CI builds and pushes a Docker image to GHCR on any `v*.*.*` tag. ArgoCD Image Updater detects the new tag (semver strategy) and syncs the cluster automatically.

---

## Local Development

```bash
docker compose -f docker-compose.dev.yml up --build
```

App available at `http://localhost:8000`.

### Git hooks

After cloning, activate the pre-commit lint check and post-commit auto-tagger:

```bash
git config core.hooksPath .githooks
```

The post-commit hook tags HEAD automatically whenever the commit message starts with `vX.Y.Z:`.

### Migrations

Migrations run automatically on startup via `run_migrations()` in `on_startup()`. To add a migration, drop an idempotent script in `scripts/` and register it in `scripts/run_migrations.py`.

---

## Data Storage

- **Local**: SQLite file in `/data`
- **Kubernetes**: Longhorn persistent volume mounted at `/data`

No database files are stored in this repository.
