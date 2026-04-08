# Mana Archive

A coherent FastAPI rebuild of the Mana Archive card inventory app.

## Features

- CSV import preview and commit
- Manual exact-card import
- Scryfall metadata lookup and refresh
- Finish-aware pricing (normal / foil / etched)
- Collection browse, search, filter, sort
- Drawer/slot location tracking
- Pending placement workflow
- Drawer views
- Audit log and import batches
- Undo last import / undo last batch
- Deck support (pull to deck / return to collection)
- Re-sort rows by price into drawers

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Notes

- SQLite database is stored at `data/mana_archive.db`
- This version uses `create_all()` for table creation, not Alembic migrations.
- CSV import expects either `Scryfall ID` or `set_code + collector_number`.
