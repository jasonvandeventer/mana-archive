# Mana-Archive

A physical inventory management system for 10,000+ Magic: The Gathering cards,
built with Python, Streamlit, SQLModel, and SQLite.

## Features

- **6-Drawer Physical Map** – Cards are sorted into one of six physical drawers
  based on price and alphabetical name range.
- **Scryfall Integration** – Images and metadata are fetched from the Scryfall
  API on import.
- **JustTCG Pricing** – Prices are fetched from JustTCG when `JUSTTCG_API_KEY` is
  set (more current than Scryfall). Falls back to Scryfall prices otherwise.
- **Atomic Imports** – CSV or manual imports update the Card record, compute the
  drawer assignment, and write a TransactionLog entry in a single database
  transaction.
- **Pending Placement Gate** – Imported cards start as `is_placed=False` and
  appear in a dedicated tab until you confirm they've been physically filed.
- **Auto Re-indexing** – Positions within a drawer are kept alphabetically
  contiguous; inserting or removing a card automatically re-numbers its neighbours.
- **Deck Builder** – Pull cards from drawers into named virtual decks; return
  them to re-insert with re-indexing.
- **Audit Log** – Every import, confirmation, pull, and move is recorded
  immutably in `TransactionLog`.
- **Rotating File Logs** – Application logs rotate at 5 MB, keeping 3 backups
  in `logs/mana_archive.log`.

## Drawer Map

Cards are sorted first by price, then by **set code**, then by **collector number** within each drawer.

| Drawer | Contents                                        |
|--------|-------------------------------------------------|
| 1      | Value cards  (price ≥ $5)                       |
| 2      | Set code starts A–D  (price < $5)              |
| 3      | Set code starts E–L  (price < $5)              |
| 4      | Set code starts M–R  (price < $5)              |
| 5      | Set code starts S–Z  (price < $5)              |
| 6      | Set code starts with a non-letter (e.g. `2x2`) |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Launch the app
streamlit run app.py
```

The SQLite database is created automatically at `data/mana_archive.db`.

### Optional: JustTCG Pricing

For more current market prices, set `JUSTTCG_API_KEY` in your environment (or a
`.env` file with `python-dotenv`):

```bash
export JUSTTCG_API_KEY=tcg_your_api_key_here
```

Get an API key at [justtcg.com](https://justtcg.com). Without it, prices come
from Scryfall.

## CSV Import Format

```csv
name,set,quantity,finish
Lightning Bolt,lea,4,nonfoil
Black Lotus,lea,1,nonfoil
Time Walk,lea,2,foil
```

Alternatively, supply `scryfall_id` instead of (or alongside) `name`.

| Column       | Required | Notes                                              |
|--------------|----------|----------------------------------------------------|
| `name`       | Yes*     | Card name. Required if `scryfall_id` is absent.   |
| `scryfall_id`| Yes*     | Scryfall UUID. Overrides `name` if both provided. |
| `set`        | No       | Scryfall set code (e.g. `lea`, `m10`).            |
| `quantity`   | No       | Defaults to 1.                                    |
| `finish`     | No       | `nonfoil` (default), `foil`, or `etched`.         |

## Project Layout

```
collector/
├── app.py                        # Streamlit entry point
├── requirements.txt
├── data/                         # SQLite database (auto-created)
├── logs/                         # Rotating log files (auto-created)
└── mana_archive/
    ├── models.py                 # SQLModel ORM models
    ├── database.py               # Engine, session factory, table init
    ├── sorter.py                 # Drawer assignment logic
    ├── scryfall.py               # Scryfall API client
    ├── inventory_service.py      # Core business logic
    └── pages/
        ├── import_cards.py       # CSV / manual / batch import UI
        ├── pending_placement.py  # Pending confirmation UI
        ├── browse_collection.py  # Search & filter collection UI
        ├── deck_builder.py       # Pull cards into decks UI
        └── audit_log.py          # Transaction history UI
```


## Runtime configuration

- `JUSTTCG_API_KEY`: enables JustTCG price refreshes.
- `DATABASE_URL`: optional. Defaults to local SQLite. Set this to a PostgreSQL connection string when you are ready to migrate.
