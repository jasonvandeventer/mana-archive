"""Drawer read services.

Drawers are a presentation of inventory rows, not independent ownership
containers. Every query is scoped by InventoryRow.user_id.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from app.models import InventoryRow


def list_drawer_groups(session: Session, user_id: int) -> dict[str, list[InventoryRow]]:
    """Return placed inventory rows grouped by drawer for one user."""
    rows = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card), joinedload(InventoryRow.storage_location))
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.is_pending.is_(False),
        )
        .all()
    )

    grouped: dict[str, list[InventoryRow]] = {}
    for row in rows:
        grouped.setdefault(row.drawer or "-", []).append(row)

    return grouped


def list_rows_for_drawer(session: Session, drawer: str, user_id: int) -> list[InventoryRow]:
    """Return placed rows for one user's drawer."""
    return (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card), joinedload(InventoryRow.storage_location))
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.drawer == drawer,
            InventoryRow.is_pending.is_(False),
        )
        .order_by(InventoryRow.slot.asc(), InventoryRow.id.asc())
        .all()
    )
