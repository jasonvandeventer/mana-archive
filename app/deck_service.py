from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.audit_service import log_transaction
from app.models import Deck, DeckItem, InventoryRow


def create_deck(session: Session, name: str, format_name: str = "", notes: str = "") -> Deck:
    deck = Deck(name=name.strip(), format=format_name.strip() or None, notes=notes.strip() or None)
    session.add(deck)
    session.commit()
    session.refresh(deck)
    return deck


def list_decks(session, user_id: int | None = None) -> list[Deck]:
    return (
        session.query(Deck)
        .options(joinedload(Deck.items).joinedload(DeckItem.card))
        .filter(Deck.user_id == user_id)
        .order_by(Deck.name.asc())
        .all()
    )


def get_deck(session: Session, deck_id: int) -> Deck | None:
    return (
        session.query(Deck)
        .options(joinedload(Deck.items).joinedload(DeckItem.card))
        .filter(Deck.id == deck_id)
        .first()
    )


def pull_card_to_deck(
    session: Session,
    user_id: int,
    deck_id: int,
    inventory_row_id: int,
    quantity: int,
) -> bool:
    row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.id == inventory_row_id,
            InventoryRow.user_id == user_id,
        )
        .first()
    )

    deck = session.query(Deck).filter(Deck.id == deck_id).first()

    if not row or not deck or quantity < 1 or row.quantity < quantity:
        return False

    row.quantity -= quantity
    row.updated_at = datetime.utcnow()

    deck_item = (
        session.query(DeckItem)
        .filter(DeckItem.deck_id == deck_id)
        .filter(DeckItem.card_id == row.card_id)
        .filter(DeckItem.finish == row.finish)
        .first()
    )

    if deck_item:
        deck_item.quantity += quantity
    else:
        deck_item = DeckItem(
            deck_id=deck_id,
            card_id=row.card_id,
            finish=row.finish,
            quantity=quantity,
        )
        session.add(deck_item)
        session.flush()

    if row.quantity <= 0:
        session.delete(row)

    log_transaction(
        session=session,
        event_type="pull_to_deck",
        card_id=deck_item.card_id,
        finish=deck_item.finish,
        quantity_delta=-quantity,
        source_location="collection",
        destination_location=f"deck:{deck.name}",
        note=f"Pulled into deck {deck.name}",
    )

    session.commit()
    return True


def return_card_from_deck(
    session: Session,
    user_id: int,
    deck_item_id: int,
    drawer: str = "",
    slot: str = "",
) -> bool:
    deck_item = (
        session.query(DeckItem)
        .options(joinedload(DeckItem.deck))
        .filter(DeckItem.id == deck_item_id)
        .first()
    )

    if not deck_item:
        return False

    existing_row = (
        session.query(InventoryRow)
        .filter(InventoryRow.card_id == deck_item.card_id)
        .filter(InventoryRow.finish == deck_item.finish)
        .filter(InventoryRow.drawer == (drawer.strip() or None))
        .filter(InventoryRow.slot == (slot.strip() or None))
        .filter(InventoryRow.is_pending.is_(True))
        .filter(InventoryRow.user_id == user_id)
        .first()
    )

    if existing_row:
        existing_row.quantity += deck_item.quantity
        existing_row.is_pending = True
        existing_row.updated_at = datetime.utcnow()
    else:
        existing_row = InventoryRow(
            user_id=user_id,
            card_id=deck_item.card_id,
            finish=deck_item.finish,
            quantity=deck_item.quantity,
            drawer=drawer.strip() or None,
            slot=slot.strip() or None,
            is_pending=True,
        )
        session.add(existing_row)
        session.flush()

    log_transaction(
        session=session,
        event_type="return_from_deck",
        card_id=deck_item.card_id,
        finish=deck_item.finish,
        quantity_delta=deck_item.quantity,
        source_location=f"deck:{deck_item.deck.name}",
        destination_location="collection",
        inventory_row_id=existing_row.id,
        note=f"Returned from deck {deck_item.deck.name}",
    )

    session.delete(deck_item)
    session.commit()
    return True


def delete_deck(session: Session, deck_id: int) -> bool:
    deck = get_deck(session, deck_id)
    if not deck:
        return False

    for item in list(deck.items):
        session.delete(item)

    session.delete(deck)
    session.commit()
    return True
