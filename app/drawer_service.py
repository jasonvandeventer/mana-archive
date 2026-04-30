from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models import InventoryRow


def list_drawer_groups(session: Session, user_id: int) -> dict[str, list[InventoryRow]]:
    rows = (
        session.query(InventoryRow)
        .options(
            joinedload(InventoryRow.card),
            joinedload(InventoryRow.storage_location),
        )
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.is_pending.is_(False),
        )
        .all()
    )

    grouped: dict[str, list[InventoryRow]] = {}
    for row in rows:
        drawer = row.drawer or "-"
        grouped.setdefault(drawer, []).append(row)

    return grouped


def list_rows_for_drawer(
    session: Session,
    drawer: str,
    user_id: int,
) -> list[InventoryRow]:
    return (
        session.query(InventoryRow)
        .options(
            joinedload(InventoryRow.card),
            joinedload(InventoryRow.storage_location),
        )
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.drawer == drawer,
            InventoryRow.is_pending.is_(False),
        )
        .order_by(InventoryRow.slot.asc(), InventoryRow.id.asc())
        .all()
    )
