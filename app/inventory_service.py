from __future__ import annotations

from datetime import datetime
from typing import Iterable
import re

from sqlalchemy.orm import Session, joinedload

from app.audit_service import log_transaction
from app.models import Card, InventoryRow, TransactionLog
from app.pricing import effective_price
from app.scryfall import fetch_card_by_scryfall_id, fetch_card_traits

VALUE_THRESHOLD = 5.0
_BASIC_LAND_NAMES = {"plains", "island", "swamp", "mountain", "forest", "wastes"}
DRAWER_LABELS = {
    "1": "Drawer 1 – Value ($5+)",
    "2": "Drawer 2 – Sets A–D",
    "3": "Drawer 3 – Sets E–L",
    "4": "Drawer 4 – Sets M–R",
    "5": "Drawer 5 – Sets S–Z",
    "6": "Drawer 6 – Numeric sets / basics",
}


def collector_sort_key(value: str | None) -> tuple[int, str, str]:
    text = (value or "").strip().lower()
    match = re.match(r"^(\d+)([a-z]*)$", text)
    if match:
        return (0, f"{int(match.group(1)):09d}", match.group(2))
    return (1, text, "")


def get_drawer_label(drawer: str | None) -> str:
    return DRAWER_LABELS.get(str(drawer or "").strip(), f"Drawer {drawer or '-'}")


def is_basic_land_candidate(card: Card, finish: str) -> bool:
    if (finish or "").strip().lower() != "normal":
        return False
    type_line = (card.type_line or "").lower()
    if "basic land" not in type_line:
        return False
    if (card.name or "").strip().lower() not in _BASIC_LAND_NAMES:
        return False
    traits = fetch_card_traits(card.scryfall_id)
    if traits is not None:
        return traits["is_basic_land"] and not traits["is_full_art"]
    return True


def assign_drawer(card: Card, finish: str) -> int:
    if effective_price(card, finish) >= VALUE_THRESHOLD:
        return 1
    if is_basic_land_candidate(card, finish):
        return 6
    first_char = (card.set_code or "").strip().lower()[:1]
    if not first_char or first_char.isdigit():
        return 6
    if "a" <= first_char <= "d":
        return 2
    if "e" <= first_char <= "l":
        return 3
    if "m" <= first_char <= "r":
        return 4
    if "s" <= first_char <= "z":
        return 5
    return 6


def drawer_sort_key(row: InventoryRow) -> tuple:
    """Return the in-drawer sort key for an inventory row.

    Drawer 6 has three explicit sections:
    1. Cards whose set codes begin with a numeral
    2. Normal-finish basic lands (non-full-art)
    3. Miscellaneous fallback rows
    """
    card = row.card
    drawer = assign_drawer(card, row.finish)
    set_code = (card.set_code or "").strip().lower()
    collector = collector_sort_key(card.collector_number)
    name = (card.name or "").strip().lower()

    if drawer == 1:
        return (set_code, collector, name, row.id)

    if drawer == 6:
        first_char = set_code[:1]
        is_numeric_set = first_char.isdigit()
        is_basic = is_basic_land_candidate(card, row.finish)

        # Section 1: numeric-prefixed set codes
        if is_numeric_set:
            return (0, set_code, collector, name, row.id)

        # Section 2: basic lands by type, then set, then collector
        if is_basic:
            return (
                1,
                basic_land_type_sort_key(card),
                set_code,
                collector,
                name,
                row.id,
            )

        # Section 3: misc fallback
        return (2, set_code, collector, name, row.id)

    return (set_code, collector, name, row.id)


def basic_land_type_sort_key(card: Card) -> tuple[int, str]:
    """Sort basic lands by land type, then name as a fallback"""
    name = (card.name or "").strip().lower()
    order = {
        "plains": 0,
        "island": 1,
        "swamp": 2,
        "mountain": 3,
        "forest": 4,
        "wastes": 5,
    }
    return (order.get(name, 99), name)


def get_or_create_card(
    session: Session, scryfall_id: str, card_data: dict | None = None
) -> Card | None:
    existing = session.query(Card).filter(Card.scryfall_id == scryfall_id).first()
    if existing:
        payload = card_data
        if payload:
            existing.name = payload["name"]
            existing.set_code = payload["set_code"]
            existing.set_name = payload["set_name"]
            existing.collector_number = payload["collector_number"]
            existing.rarity = payload["rarity"]
            existing.image_url = payload["image_url"]
            existing.type_line = payload["type_line"]
            existing.oracle_text = payload["oracle_text"]
            existing.price_usd = payload["price_usd"]
            existing.price_usd_foil = payload["price_usd_foil"]
            existing.price_usd_etched = payload["price_usd_etched"]
            existing.updated_at = datetime.utcnow()
            session.flush()
        elif (
            not existing.image_url or not existing.type_line or not existing.oracle_text
        ):
            payload = fetch_card_by_scryfall_id(scryfall_id)
            if payload:
                existing.name = payload["name"]
                existing.set_code = payload["set_code"]
                existing.set_name = payload["set_name"]
                existing.collector_number = payload["collector_number"]
                existing.rarity = payload["rarity"]
                existing.image_url = payload["image_url"]
                existing.type_line = payload["type_line"]
                existing.oracle_text = payload["oracle_text"]
                existing.price_usd = payload["price_usd"]
                existing.price_usd_foil = payload["price_usd_foil"]
                existing.price_usd_etched = payload["price_usd_etched"]
                existing.updated_at = datetime.utcnow()
                session.flush()
        return existing
    payload = card_data or fetch_card_by_scryfall_id(scryfall_id)
    if not payload:
        return None
    card = Card(**payload, updated_at=datetime.utcnow())
    session.add(card)
    session.flush()
    return card


def find_matching_inventory_row(
    session: Session,
    card_id: int,
    finish: str,
    drawer: str | None,
    slot: str | None,
    is_pending: bool,
) -> InventoryRow | None:
    return (
        session.query(InventoryRow)
        .filter(InventoryRow.card_id == card_id)
        .filter(InventoryRow.finish == finish)
        .filter(InventoryRow.drawer == drawer)
        .filter(InventoryRow.slot == slot)
        .filter(InventoryRow.is_pending == is_pending)
        .first()
    )


def create_or_merge_inventory_row(
    session: Session,
    card_id: int,
    finish: str,
    quantity: int,
    drawer: str | None = None,
    slot: str | None = None,
    is_pending: bool = True,
    notes: str | None = None,
) -> InventoryRow:
    existing = find_matching_inventory_row(
        session, card_id, finish, drawer, slot, is_pending
    )
    if existing:
        existing.quantity += quantity
        existing.updated_at = datetime.utcnow()
        if notes:
            existing.notes = notes
        session.flush()
        return existing
    row = InventoryRow(
        card_id=card_id,
        finish=finish,
        quantity=quantity,
        drawer=drawer,
        slot=slot,
        is_pending=is_pending,
        notes=notes,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def list_inventory_rows(
    session: Session,
    search: str = "",
    finish: str = "",
    drawer: str = "",
    sort: str = "newest",
) -> list[InventoryRow]:
    query = (
        session.query(InventoryRow).options(joinedload(InventoryRow.card)).join(Card)
    )
    if search.strip():
        query = query.filter(Card.name.ilike(f"%{search.strip()}%"))
    if finish.strip():
        query = query.filter(InventoryRow.finish == finish.strip().lower())
    if drawer.strip():
        query = query.filter(InventoryRow.drawer == drawer.strip())
    rows = query.all()
    if sort == "name":
        rows.sort(
            key=lambda r: (
                (r.card.name or "").lower(),
                (r.card.set_code or "").lower(),
                collector_sort_key(r.card.collector_number),
            )
        )
    elif sort == "set":
        rows.sort(
            key=lambda r: (
                (r.card.set_code or "").lower(),
                collector_sort_key(r.card.collector_number),
                (r.card.name or "").lower(),
            )
        )
    elif sort == "value":
        rows.sort(
            key=lambda r: effective_price(r.card, r.finish) * r.quantity, reverse=True
        )
    elif sort == "placement":
        rows.sort(key=lambda r: (assign_drawer(r.card, r.finish), drawer_sort_key(r)))
    else:
        rows.sort(key=lambda r: r.id, reverse=True)
    return rows


def update_inventory_location(
    session: Session, row_id: int, drawer: str | None, slot: str | None
) -> InventoryRow | None:
    row = session.query(InventoryRow).filter(InventoryRow.id == row_id).first()
    if not row:
        return None
    old_location = f"drawer={row.drawer or '-'} slot={row.slot or '-'}"
    row.drawer = (drawer or "").strip() or None
    row.slot = (slot or "").strip() or None
    row.updated_at = datetime.utcnow()
    log_transaction(
        session=session,
        event_type="location_updated",
        card_id=row.card_id,
        finish=row.finish,
        quantity_delta=0,
        source_location=old_location,
        destination_location=f"drawer={row.drawer or '-'} slot={row.slot or '-'}",
        inventory_row_id=row.id,
        note="Inventory location updated",
    )
    session.commit()
    return row


def list_pending_rows(session: Session) -> list[InventoryRow]:
    rows = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card))
        .filter(InventoryRow.is_pending.is_(True))
        .all()
    )
    rows.sort(key=lambda r: (assign_drawer(r.card, r.finish), drawer_sort_key(r)))
    return rows


def confirm_pending_row(session: Session, row_id: int) -> InventoryRow | None:
    row = session.query(InventoryRow).filter(InventoryRow.id == row_id).first()
    if not row:
        return None
    row.is_pending = False
    row.updated_at = datetime.utcnow()
    log_transaction(
        session=session,
        event_type="placement_confirmed",
        card_id=row.card_id,
        finish=row.finish,
        quantity_delta=0,
        source_location="pending",
        destination_location=f"drawer={row.drawer or '-'} slot={row.slot or '-'}",
        inventory_row_id=row.id,
        note="Pending row confirmed as placed",
    )
    session.commit()
    return row


def confirm_all_pending(session: Session) -> int:
    rows = session.query(InventoryRow).filter(InventoryRow.is_pending.is_(True)).all()
    count = 0
    for row in rows:
        row.is_pending = False
        row.updated_at = datetime.utcnow()
        log_transaction(
            session=session,
            event_type="placement_confirmed",
            card_id=row.card_id,
            finish=row.finish,
            quantity_delta=0,
            source_location="pending",
            destination_location=f"drawer={row.drawer or '-'} slot={row.slot or '-'}",
            inventory_row_id=row.id,
            note="Pending row confirmed as placed",
        )
        count += 1
    session.commit()
    return count


def adjust_inventory_row_quantity(
    session: Session,
    row_id: int,
    quantity: int,
    event_type: str,
    note: str | None = None,
) -> InventoryRow | None:
    valid_event_types = {"remove", "sold", "traded", "row_deleted"}
    if event_type not in valid_event_types:
        raise ValueError(f"Unsupported event_type: {event_type}")

    row = session.query(InventoryRow).filter(InventoryRow.id == row_id).first()
    if not row:
        raise ValueError("Inventory row not found.")
    if quantity <= 0:
        raise ValueError("Quantity must be at least 1.")
    if quantity > row.quantity:
        raise ValueError("Cannot remove more than the row quantity.")

    source_location = (
        "pending"
        if row.is_pending
        else f"drawer={row.drawer or '-'} slot={row.slot or '-'}"
    )
    log_transaction(
        session=session,
        event_type=event_type,
        card_id=row.card_id,
        finish=row.finish,
        quantity_delta=-quantity,
        source_location=source_location,
        destination_location=None,
        inventory_row_id=row.id,
        note=note,
        flush=False,
    )

    if quantity == row.quantity:
        session.delete(row)
        return None

    row.quantity -= quantity
    row.updated_at = datetime.utcnow()
    return row


def delete_inventory_row(session: Session, row_id: int) -> bool:
    row = session.query(InventoryRow).filter(InventoryRow.id == row_id).first()
    if not row:
        return False
    adjust_inventory_row_quantity(
        session=session,
        row_id=row_id,
        quantity=row.quantity,
        event_type="row_deleted",
        note=f"Deleted inventory row {row_id}",
    )
    session.commit()
    return True


def undo_last_import(session: Session) -> bool:
    last_import = (
        session.query(TransactionLog)
        .filter(TransactionLog.event_type == "import")
        .order_by(TransactionLog.id.desc())
        .first()
    )
    if not last_import or not last_import.inventory_row_id:
        return False
    row = (
        session.query(InventoryRow)
        .filter(InventoryRow.id == last_import.inventory_row_id)
        .first()
    )
    if row:
        row.quantity -= abs(last_import.quantity_delta)
        row.updated_at = datetime.utcnow()
        if row.quantity <= 0:
            session.delete(row)
    session.flush()
    log_transaction(
        session=session,
        event_type="undo_import",
        card_id=last_import.card_id,
        finish=last_import.finish,
        quantity_delta=-abs(last_import.quantity_delta),
        batch_id=last_import.batch_id,
        inventory_row_id=last_import.inventory_row_id,
        note=f"Undid import log {last_import.id}",
    )
    session.commit()
    return True


def undo_last_batch(session: Session, batch_id: int) -> int:
    logs = (
        session.query(TransactionLog)
        .filter(TransactionLog.batch_id == batch_id)
        .filter(TransactionLog.event_type == "import")
        .order_by(TransactionLog.id.desc())
        .all()
    )
    undone = 0
    for log in logs:
        row = (
            session.query(InventoryRow)
            .filter(InventoryRow.id == log.inventory_row_id)
            .first()
        )
        if row:
            row.quantity -= abs(log.quantity_delta)
            row.updated_at = datetime.utcnow()
            if row.quantity <= 0:
                session.delete(row)
        log_transaction(
            session=session,
            event_type="undo_batch_import",
            card_id=log.card_id,
            finish=log.finish,
            quantity_delta=-abs(log.quantity_delta),
            batch_id=log.batch_id,
            inventory_row_id=log.inventory_row_id,
            note=f"Undid import log {log.id} from batch {batch_id}",
        )
        undone += 1
    session.commit()
    return undone


def resort_collection(session: Session, row_ids: Iterable[int] | None = None) -> int:
    query = session.query(InventoryRow).options(joinedload(InventoryRow.card))
    if row_ids is not None:
        row_ids = list(row_ids)
        if not row_ids:
            return 0
        query = query.filter(InventoryRow.id.in_(row_ids))
    rows = query.all()
    rows.sort(key=lambda r: (assign_drawer(r.card, r.finish), drawer_sort_key(r)))
    grouped: dict[int, list[InventoryRow]] = {i: [] for i in range(1, 7)}
    for row in rows:
        grouped[assign_drawer(row.card, row.finish)].append(row)
    updated = 0
    for drawer_number, drawer_rows in grouped.items():
        for index, row in enumerate(drawer_rows, start=1):
            target_drawer = str(drawer_number)
            target_slot = str(index)
            if row.drawer != target_drawer or row.slot != target_slot:
                old = f"drawer={row.drawer or '-'} slot={row.slot or '-'}"
                row.drawer = target_drawer
                row.slot = target_slot
                row.updated_at = datetime.utcnow()
                log_transaction(
                    session=session,
                    event_type="resort",
                    card_id=row.card_id,
                    finish=row.finish,
                    quantity_delta=0,
                    source_location=old,
                    destination_location=f"drawer={target_drawer} slot={target_slot}",
                    inventory_row_id=row.id,
                    note="Auto-sorted collection row by placement rules",
                )
                updated += 1
    return updated
