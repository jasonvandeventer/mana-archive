from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session, joinedload

from app.models import InventoryRow


def _slot_sort_key(value: str | None) -> tuple[int, str]:
    text = (value or "").strip()
    if text.isdigit():
        return (0, f"{int(text):09d}")
    return (1, text.lower())



def list_drawer_groups(session: Session) -> dict[str, list[InventoryRow]]:
    rows = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card))
        .filter(InventoryRow.drawer.isnot(None))
        .all()
    )
    rows.sort(key=lambda r: ((r.drawer or "").lower(), _slot_sort_key(r.slot), r.id))

    grouped: dict[str, list[InventoryRow]] = defaultdict(list)
    for row in rows:
        grouped[row.drawer or "Unassigned"].append(row)
    return dict(grouped)



def list_rows_for_drawer(session: Session, drawer: str) -> list[InventoryRow]:
    rows = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card))
        .filter(InventoryRow.drawer == drawer)
        .all()
    )
    rows.sort(key=lambda r: (_slot_sort_key(r.slot), r.id))
    return rows
