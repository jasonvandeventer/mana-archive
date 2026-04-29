from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session, joinedload

from app.models import InventoryRow, StorageLocation


def _slot_sort_key(value: str | None) -> tuple[int, str]:
    text = (value or "").strip()
    if text.isdigit():
        return (0, f"{int(text):09d}")
    return (1, text.lower())


def _drawer_number_from_location(location: StorageLocation | None) -> str:
    if not location or location.type != "drawer":
        return "Unassigned"

    return location.name.replace("Drawer", "").strip() or "Unassigned"


def list_drawer_groups(session: Session) -> dict[str, list[InventoryRow]]:
    rows = (
        session.query(InventoryRow)
        .options(
            joinedload(InventoryRow.card),
            joinedload(InventoryRow.storage_location),
        )
        .filter(InventoryRow.storage_location_id.isnot(None))
        .all()
    )

    rows.sort(
        key=lambda r: (
            _drawer_number_from_location(r.storage_location),
            _slot_sort_key(r.slot),
            r.id,
        )
    )

    grouped: dict[str, list[InventoryRow]] = defaultdict(list)
    for row in rows:
        grouped[_drawer_number_from_location(row.storage_location)].append(row)

    return dict(grouped)


def list_rows_for_drawer(session: Session, drawer: str) -> list[InventoryRow]:
    location_name = f"Drawer {drawer}"

    rows = (
        session.query(InventoryRow)
        .join(InventoryRow.storage_location)
        .options(
            joinedload(InventoryRow.card),
            joinedload(InventoryRow.storage_location),
        )
        .filter(StorageLocation.name == location_name)
        .filter(StorageLocation.type == "drawer")
        .all()
    )

    rows.sort(key=lambda r: (_slot_sort_key(r.slot), r.id))
    return rows
