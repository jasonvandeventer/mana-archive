from sqlalchemy.orm import Session, joinedload

from app.models import Deck, InventoryRow, StorageLocation
from app.pricing import effective_price

VALID_LOCATION_TYPES = {"root", "drawer", "binder", "box", "deck", "other"}


def list_locations(session: Session, user_id: int) -> list[StorageLocation]:
    return (
        session.query(StorageLocation)
        .options(joinedload(StorageLocation.parent))
        .filter(StorageLocation.user_id == user_id)
        .order_by(
            StorageLocation.parent_id.nullsfirst(), StorageLocation.sort_order, StorageLocation.name
        )
        .all()
    )


def get_location(session: Session, location_id: int, user_id: int) -> StorageLocation | None:
    return (
        session.query(StorageLocation)
        .filter(
            StorageLocation.id == location_id,
            StorageLocation.user_id == user_id,
        )
        .first()
    )


def create_location(
    session: Session,
    user_id: int,
    name: str,
    type: str,
    parent_id: int | None = None,
    sort_order: int = 0,
) -> StorageLocation:
    name = name.strip()
    type = type.strip().lower() or "other"

    if not name:
        raise ValueError("Location name is required.")

    if type not in VALID_LOCATION_TYPES:
        raise ValueError(f"Invalid location type: {type}")

    existing = (
        session.query(StorageLocation)
        .filter(
            StorageLocation.user_id == user_id,
            StorageLocation.name == name,
        )
        .first()
    )
    if existing:
        raise ValueError(f"A location named '{name}' already exists.")

    if parent_id is not None:
        parent = get_location(session, parent_id, user_id)
        if parent is None:
            raise ValueError("Parent location does not exist.")

    location = StorageLocation(
        user_id=user_id,
        name=name,
        type=type,
        parent_id=parent_id,
        sort_order=sort_order,
    )
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def get_location_summary(session: Session, user_id: int) -> list[dict]:
    locations = list_locations(session, user_id=user_id)

    summaries = []
    for location in locations:
        rows = (
            session.query(InventoryRow)
            .options(joinedload(InventoryRow.card))
            .filter(
                InventoryRow.user_id == user_id,
                InventoryRow.storage_location_id == location.id,
            )
            .all()
        )

        quantity = sum(row.quantity for row in rows)
        total_value = 0.0

        for row in rows:
            price = effective_price(row.card, row.finish) or 0.0
            total_value += price * row.quantity

        is_orphaned_deck = (
            location.type == "deck"
            and not session.query(Deck).filter(Deck.storage_location_id == location.id).first()
        )
        is_deletable = (
            len(rows) == 0
            and location.type not in ("root",)
            and (location.type != "deck" or is_orphaned_deck)
        )

        summaries.append(
            {
                "location": location,
                "row_count": len(rows),
                "quantity": quantity,
                "total_value": total_value,
                "is_deletable": is_deletable,
            }
        )

    return summaries


def delete_location(session: Session, location_id: int, user_id: int) -> None:
    location = get_location(session, location_id=location_id, user_id=user_id)
    if location is None:
        raise ValueError("Location not found.")
    if location.type == "root":
        raise ValueError("This location cannot be deleted directly.")
    if location.type == "deck":
        linked_deck = session.query(Deck).filter(Deck.storage_location_id == location_id).first()
        if linked_deck:
            raise ValueError("Delete the deck from the Decks page to remove this location.")
    has_rows = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.storage_location_id == location_id,
        )
        .first()
    )
    if has_rows:
        raise ValueError(
            "Cannot delete a location that still contains cards. Move or remove them first."
        )
    has_children = (
        session.query(StorageLocation).filter(StorageLocation.parent_id == location_id).first()
    )
    if has_children:
        raise ValueError("Cannot delete a location that has child locations.")
    session.delete(location)
    session.commit()


def list_rows_for_location(
    session: Session,
    user_id: int,
    location_id: int,
) -> list[InventoryRow]:
    location = get_location(session, location_id=location_id, user_id=user_id)
    if location is None:
        raise ValueError("Location does not exist.")

    return (
        session.query(InventoryRow)
        .options(
            joinedload(InventoryRow.card),
            joinedload(InventoryRow.storage_location),
        )
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.storage_location_id == location_id,
        )
        .order_by(InventoryRow.slot.asc())
        .all()
    )
