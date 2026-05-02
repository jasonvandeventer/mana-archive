from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.audit_service import log_transaction
from app.models import Deck, InventoryRow, StorageLocation


def create_deck(
    session: Session,
    user_id: int,
    name: str,
    format_name: str = "",
    notes: str = "",
) -> Deck:
    deck_name = name.strip()

    location = StorageLocation(
        user_id=user_id,
        name=deck_name,
        type="deck",
        parent_id=None,
        sort_order=0,
    )
    session.add(location)
    session.flush()

    deck = Deck(
        user_id=user_id,
        storage_location_id=location.id,
        name=deck_name,
        format=format_name.strip() or None,
        notes=notes.strip() or None,
    )
    session.add(deck)
    session.commit()
    session.refresh(deck)
    return deck


def list_decks(session: Session, user_id: int) -> list[Deck]:
    decks = (
        session.query(Deck)
        .options(joinedload(Deck.storage_location))
        .filter(Deck.user_id == user_id)
        .order_by(Deck.name.asc())
        .all()
    )

    for deck in decks:
        if not deck.storage_location_id:
            deck.card_count = 0
            continue

        deck.card_count = (
            session.query(InventoryRow)
            .filter(
                InventoryRow.user_id == user_id,
                InventoryRow.storage_location_id == deck.storage_location_id,
            )
            .count()
        )

    return decks


def get_deck(session: Session, deck_id: int, user_id: int) -> Deck | None:
    return (
        session.query(Deck)
        .options(joinedload(Deck.storage_location))
        .filter(
            Deck.id == deck_id,
            Deck.user_id == user_id,
        )
        .first()
    )


def pull_card_to_deck(
    session: Session,
    user_id: int,
    deck_id: int,
    inventory_row_id: int,
    quantity: int,
) -> bool:
    if quantity < 1:
        return False

    deck = (
        session.query(Deck)
        .filter(
            Deck.id == deck_id,
            Deck.user_id == user_id,
        )
        .first()
    )

    row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.id == inventory_row_id,
            InventoryRow.user_id == user_id,
        )
        .first()
    )

    if not row or not deck or not deck.storage_location_id or row.quantity < quantity:
        return False

    existing_deck_row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.card_id == row.card_id,
            InventoryRow.finish == row.finish,
            InventoryRow.storage_location_id == deck.storage_location_id,
            InventoryRow.is_pending.is_(False),
        )
        .first()
    )

    if existing_deck_row:
        existing_deck_row.quantity += quantity
        existing_deck_row.updated_at = datetime.utcnow()
    else:
        existing_deck_row = InventoryRow(
            user_id=user_id,
            card_id=row.card_id,
            storage_location_id=deck.storage_location_id,
            finish=row.finish,
            quantity=quantity,
            drawer=None,
            slot=None,
            is_pending=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(existing_deck_row)
        session.flush()

    row.quantity -= quantity
    row.updated_at = datetime.utcnow()

    if row.quantity <= 0:
        session.delete(row)

    log_transaction(
        session=session,
        user_id=user_id,
        event_type="pull_to_deck",
        card_id=existing_deck_row.card_id,
        finish=existing_deck_row.finish,
        quantity_delta=-quantity,
        source_location="collection",
        destination_location=f"deck:{deck.name}",
        inventory_row_id=existing_deck_row.id,
        note=f"Pulled into deck {deck.name}",
    )

    session.commit()
    return True


def return_card_from_deck(
    session: Session,
    user_id: int,
    deck_row_id: int,
    drawer: str = "",
    slot: str = "",
) -> bool:
    deck_row = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card))
        .join(
            Deck,
            Deck.storage_location_id == InventoryRow.storage_location_id,
        )
        .filter(
            Deck.user_id == user_id,
            InventoryRow.id == deck_row_id,
            InventoryRow.user_id == user_id,
        )
        .first()
    )

    if not deck_row:
        return False

    deck = (
        session.query(Deck)
        .filter(
            Deck.user_id == user_id,
            Deck.storage_location_id == deck_row.storage_location_id,
        )
        .first()
    )

    if not deck:
        return False

    normalized_drawer = drawer.strip() or None
    normalized_slot = slot.strip() or None

    existing_row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.card_id == deck_row.card_id,
            InventoryRow.finish == deck_row.finish,
            InventoryRow.drawer == normalized_drawer,
            InventoryRow.slot == normalized_slot,
            InventoryRow.is_pending.is_(True),
        )
        .first()
    )

    if existing_row:
        existing_row.quantity += deck_row.quantity
        existing_row.storage_location_id = None
        existing_row.is_pending = True
        existing_row.updated_at = datetime.utcnow()
    else:
        existing_row = InventoryRow(
            user_id=user_id,
            card_id=deck_row.card_id,
            finish=deck_row.finish,
            quantity=deck_row.quantity,
            drawer=normalized_drawer,
            slot=normalized_slot,
            storage_location_id=None,
            is_pending=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(existing_row)
        session.flush()

    log_transaction(
        session=session,
        user_id=user_id,
        event_type="return_from_deck",
        card_id=deck_row.card_id,
        finish=deck_row.finish,
        quantity_delta=deck_row.quantity,
        source_location=f"deck:{deck.name}",
        destination_location="collection",
        inventory_row_id=existing_row.id,
        note=f"Returned from deck {deck.name}",
    )

    session.delete(deck_row)
    session.commit()
    return True


def delete_deck(session: Session, deck_id: int, user_id: int) -> bool:
    deck = get_deck(session, deck_id=deck_id, user_id=user_id)
    if not deck:
        return False

    if deck.storage_location_id:
        # Delete all inventory rows in this deck
        deck_rows = (
            session.query(InventoryRow)
            .filter(
                InventoryRow.user_id == user_id,
                InventoryRow.storage_location_id == deck.storage_location_id,
            )
            .all()
        )

        for row in deck_rows:
            session.delete(row)

        # Delete the storage location itself
        location = (
            session.query(StorageLocation)
            .filter(
                StorageLocation.id == deck.storage_location_id,
                StorageLocation.user_id == user_id,
            )
            .first()
        )

        if location:
            session.delete(location)

    # Delete the deck
    session.delete(deck)
    session.commit()
    return True
