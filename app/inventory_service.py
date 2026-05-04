from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.audit_service import log_transaction
from app.models import Card, InventoryRow, StorageLocation, TransactionLog
from app.pricing import effective_price
from app.scryfall import fetch_card_by_scryfall_id, fetch_card_traits

PRICE_STALE_DAYS = 7
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


def get_location_label(row: InventoryRow) -> str:
    if row.storage_location:
        location = row.storage_location

        if location.type == "drawer":
            drawer_number = location.name.replace("Drawer", "").strip()
            return get_drawer_label(drawer_number)

        return location.name

    return get_drawer_label(row.drawer)


def basic_land_type_sort_key(card: Card) -> tuple[int, str]:
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
    price = effective_price(card, finish) or 0.0
    if price >= VALUE_THRESHOLD:
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

        if is_numeric_set:
            return (0, set_code, collector, name, row.id)

        if is_basic:
            return (1, basic_land_type_sort_key(card), set_code, collector, name, row.id)

        return (2, set_code, collector, name, row.id)

    return (set_code, collector, name, row.id)


def get_or_create_card(
    session: Session,
    scryfall_id: str,
    card_data: dict | None = None,
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
        elif not existing.image_url or not existing.type_line or not existing.oracle_text:
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
    user_id: int,
    card_id: int,
    finish: str,
    drawer: str | None,
    slot: str | None,
    is_pending: bool,
) -> InventoryRow | None:
    return (
        session.query(InventoryRow)
        .filter(InventoryRow.user_id == user_id)
        .filter(InventoryRow.card_id == card_id)
        .filter(InventoryRow.finish == finish)
        .filter(InventoryRow.drawer == drawer)
        .filter(InventoryRow.slot == slot)
        .filter(InventoryRow.is_pending == is_pending)
        .first()
    )


def create_or_merge_inventory_row(
    session: Session,
    user_id: int,
    card_id: int,
    finish: str,
    quantity: int,
    drawer: str | None = None,
    slot: str | None = None,
    is_pending: bool = True,
    notes: str | None = None,
) -> InventoryRow:
    existing = find_matching_inventory_row(
        session=session,
        user_id=user_id,
        card_id=card_id,
        finish=finish,
        drawer=drawer,
        slot=slot,
        is_pending=is_pending,
    )

    if existing:
        existing.quantity += quantity
        existing.updated_at = datetime.utcnow()
        if notes:
            existing.notes = notes
        session.flush()
        return existing

    row = InventoryRow(
        user_id=user_id,
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


def _parse_numeric_op(value: str) -> tuple[str, float] | None:
    for op in (">=", "<=", ">", "<"):
        if value.startswith(op):
            try:
                return op, float(value[len(op) :])
            except ValueError:
                return None
    try:
        return "=", float(value)
    except ValueError:
        return None


def parse_search_query(search: str) -> dict:
    terms = search.strip().split()

    parsed: dict = {
        "name": [],
        "type": None,
        "oracle": None,
        "set": None,
        "rarity": None,
        "finish": None,
        "drawer": None,
        "color": None,
        "mana": None,
        "cmc": None,
    }

    for term in terms:
        if ":" not in term:
            parsed["name"].append(term)
            continue

        key, value = term.split(":", 1)
        key = key.strip().lower()
        value = value.strip().lower()

        if not value:
            continue

        if key in ["t", "type"]:
            parsed["type"] = value
        elif key in ["o", "oracle"]:
            parsed["oracle"] = value
        elif key in ["s", "set"]:
            parsed["set"] = value
        elif key in ["r", "rarity"]:
            parsed["rarity"] = value
        elif key == "finish":
            parsed["finish"] = value
        elif key == "drawer":
            parsed["drawer"] = value
        elif key in ["c", "color", "colors"]:
            parsed["color"] = value.upper()
        elif key in ["m", "mana"]:
            parsed["mana"] = value
        elif key == "cmc":
            parsed["cmc"] = _parse_numeric_op(value)
        else:
            parsed["name"].append(term)

    return parsed


def apply_collection_search_filters(query, search: str):
    if not search.strip():
        return query

    parsed = parse_search_query(search)

    for term in parsed["name"]:
        query = query.filter(Card.name.ilike(f"%{term}%"))

    if parsed["type"]:
        query = query.filter(Card.type_line.ilike(f"%{parsed['type']}%"))

    if parsed["oracle"]:
        query = query.filter(Card.oracle_text.ilike(f"%{parsed['oracle']}%"))

    if parsed["set"]:
        query = query.filter(Card.set_code.ilike(f"%{parsed['set']}%"))

    if parsed["rarity"]:
        query = query.filter(Card.rarity.ilike(f"%{parsed['rarity']}%"))

    if parsed["finish"]:
        query = query.filter(InventoryRow.finish == parsed["finish"])

    if parsed["drawer"]:
        query = query.filter(InventoryRow.drawer == parsed["drawer"])

    if parsed["color"]:
        for letter in parsed["color"]:
            if letter in "WUBRG":
                query = query.filter(Card.colors.contains(letter))
            elif letter == "C":
                query = query.filter((Card.colors == None) | (Card.colors == ""))  # noqa: E711

    if parsed["mana"]:
        query = query.filter(Card.mana_cost.ilike(f"%{parsed['mana']}%"))

    if parsed["cmc"]:
        op, val = parsed["cmc"]
        if op == "=":
            query = query.filter(Card.cmc == val)
        elif op == ">":
            query = query.filter(Card.cmc > val)
        elif op == "<":
            query = query.filter(Card.cmc < val)
        elif op == ">=":
            query = query.filter(Card.cmc >= val)
        elif op == "<=":
            query = query.filter(Card.cmc <= val)

    return query


def list_inventory_rows(
    session: Session,
    user_id: int,
    search: str = "",
    finish: str = "",
    drawer: str = "",
    sort: str = "newest",
    direction: str = "desc",
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[InventoryRow], int]:
    page = max(page, 1)
    per_page = max(1, min(per_page, 100))
    reverse = direction == "desc"

    base_query = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card), joinedload(InventoryRow.storage_location))
        .join(Card)
        .filter(InventoryRow.user_id == user_id)
    )

    base_query = apply_collection_search_filters(base_query, search)

    if finish.strip():
        base_query = base_query.filter(InventoryRow.finish == finish.strip().lower())

    if drawer.strip():
        base_query = base_query.join(InventoryRow.storage_location).filter(
            StorageLocation.user_id == user_id,
            StorageLocation.name == f"Drawer {drawer.strip()}",
            StorageLocation.type == "drawer",
        )

    total_count = base_query.count()

    _COLOR_ORDER = {"W": 0, "U": 1, "B": 2, "R": 3, "G": 4}

    def _color_sort_key(row: InventoryRow) -> tuple:
        colors = (row.card.colors or "").split()
        if not colors:
            return (6, "")
        if len(colors) > 1:
            return (5, " ".join(colors))
        return (_COLOR_ORDER.get(colors[0], 7), colors[0])

    if sort == "name":
        query = base_query.order_by(
            Card.name.desc() if reverse else Card.name.asc(),
            Card.set_code.desc() if reverse else Card.set_code.asc(),
            Card.collector_number.desc() if reverse else Card.collector_number.asc(),
            InventoryRow.id.desc() if reverse else InventoryRow.id.asc(),
        )
        rows = query.offset((page - 1) * per_page).limit(per_page).all()
    elif sort == "set":
        query = base_query.order_by(
            Card.set_code.desc() if reverse else Card.set_code.asc(),
            Card.collector_number.desc() if reverse else Card.collector_number.asc(),
            Card.name.desc() if reverse else Card.name.asc(),
            InventoryRow.id.desc() if reverse else InventoryRow.id.asc(),
        )
        rows = query.offset((page - 1) * per_page).limit(per_page).all()
    elif sort == "type":
        query = base_query.order_by(
            Card.type_line.desc() if reverse else Card.type_line.asc(),
            Card.name.desc() if reverse else Card.name.asc(),
            InventoryRow.id.desc() if reverse else InventoryRow.id.asc(),
        )
        rows = query.offset((page - 1) * per_page).limit(per_page).all()
    elif sort == "cmc":
        query = base_query.order_by(
            Card.cmc.desc() if reverse else Card.cmc.asc(),
            Card.name.desc() if reverse else Card.name.asc(),
            InventoryRow.id.desc() if reverse else InventoryRow.id.asc(),
        )
        rows = query.offset((page - 1) * per_page).limit(per_page).all()
    elif sort == "color":
        rows = base_query.all()
        rows.sort(key=_color_sort_key, reverse=reverse)
        rows = rows[(page - 1) * per_page : (page - 1) * per_page + per_page]
    elif sort == "placement":
        rows = base_query.all()
        rows.sort(
            key=lambda r: (assign_drawer(r.card, r.finish), drawer_sort_key(r)),
            reverse=reverse,
        )
        rows = rows[(page - 1) * per_page : (page - 1) * per_page + per_page]
    elif sort == "value":
        rows = base_query.all()
        rows.sort(key=lambda r: effective_price(r.card, r.finish) or 0.0, reverse=reverse)
        rows = rows[(page - 1) * per_page : (page - 1) * per_page + per_page]
    else:
        query = base_query.order_by(InventoryRow.id.desc() if reverse else InventoryRow.id.asc())
        rows = query.offset((page - 1) * per_page).limit(per_page).all()

    return rows, total_count


def is_price_stale(price_updated_at: datetime | None) -> bool:
    if price_updated_at is None:
        return True
    return price_updated_at < datetime.utcnow() - timedelta(days=PRICE_STALE_DAYS)


def get_inventory_row_stats(
    session: Session,
    user_id: int,
    search: str = "",
    finish: str = "",
    drawer: str = "",
) -> dict:
    query = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card))
        .join(Card)
        .filter(InventoryRow.user_id == user_id)
    )

    query = apply_collection_search_filters(query, search)

    if finish.strip():
        query = query.filter(InventoryRow.finish == finish.strip().lower())

    if drawer.strip():
        query = query.join(InventoryRow.storage_location).filter(
            StorageLocation.user_id == user_id,
            StorageLocation.name == f"Drawer {drawer.strip()}",
            StorageLocation.type == "drawer",
        )

    rows = query.all()

    total_value = 0.0
    total_cards = 0
    unique_cards = 0
    drawer_counts = {str(i): 0 for i in range(1, 7)}
    unassigned_count = 0

    for row in rows:
        price = effective_price(row.card, row.finish)
        if price is not None:
            total_value += price * row.quantity
        total_cards += row.quantity
        unique_cards += 1

        if str(row.drawer) in drawer_counts:
            drawer_counts[str(row.drawer)] += row.quantity
        else:
            unassigned_count += row.quantity

    return {
        "total_value": total_value,
        "total_cards": total_cards,
        "unique_cards": unique_cards,
        "drawer_counts": drawer_counts,
        "unassigned_count": unassigned_count,
    }


def update_inventory_location(
    session: Session,
    row_id: int,
    user_id: int,
    drawer: str | None,
    slot: str | None,
) -> InventoryRow | None:
    row = (
        session.query(InventoryRow)
        .filter(InventoryRow.id == row_id, InventoryRow.user_id == user_id)
        .first()
    )
    if not row:
        return None

    old_location = (
        "pending" if row.is_pending else f"drawer={row.drawer or '-'} slot={row.slot or '-'}"
    )

    row.drawer = (drawer or "").strip() or None
    row.slot = (slot or "").strip() or None
    row.is_pending = row.drawer is None or row.slot is None
    row.updated_at = datetime.now(UTC)

    if row.drawer:
        location = (
            session.query(StorageLocation)
            .filter(
                StorageLocation.user_id == user_id,
                StorageLocation.name == f"Drawer {row.drawer}",
                StorageLocation.type == "drawer",
            )
            .first()
        )
        row.storage_location_id = location.id if location else None
    else:
        row.storage_location_id = None

    log_transaction(
        session=session,
        user_id=user_id,
        event_type="location_updated",
        card_id=row.card_id,
        finish=row.finish,
        quantity_delta=0,
        source_location=old_location,
        destination_location=(
            "pending" if row.is_pending else f"drawer={row.drawer or '-'} slot={row.slot or '-'}"
        ),
        inventory_row_id=row.id,
        note="Inventory location updated",
    )
    session.commit()
    return row


def move_inventory_row_to_location(
    session: Session, row_id: int, user_id: int, location_id: int
) -> InventoryRow:
    row = (
        session.query(InventoryRow)
        .filter(InventoryRow.id == row_id, InventoryRow.user_id == user_id)
        .first()
    )
    if not row:
        raise ValueError("Inventory row not found.")

    new_location = (
        session.query(StorageLocation)
        .filter(StorageLocation.id == location_id, StorageLocation.user_id == user_id)
        .one_or_none()
    )
    if new_location is None:
        raise ValueError("Storage location not found.")

    old_location = row.storage_location.name if row.storage_location else "unassigned"

    row.storage_location_id = new_location.id
    row.is_pending = False
    row.updated_at = datetime.now(UTC)

    log_transaction(
        session=session,
        user_id=user_id,
        event_type="location_updated",
        card_id=row.card_id,
        finish=row.finish,
        quantity_delta=0,
        source_location=old_location,
        destination_location=new_location.name,
        inventory_row_id=row.id,
        note="Card moved to new storage location",
    )
    session.commit()
    return row


def place_imported_rows(
    session: Session, row_ids: list[int], user_id: int, location_id: int
) -> int:
    location = (
        session.query(StorageLocation)
        .filter(StorageLocation.id == location_id, StorageLocation.user_id == user_id)
        .one_or_none()
    )
    if location is None:
        raise ValueError("Storage location not found.")

    rows = (
        session.query(InventoryRow)
        .filter(InventoryRow.id.in_(row_ids), InventoryRow.user_id == user_id)
        .all()
    )
    now = datetime.now(UTC)
    for row in rows:
        row.storage_location_id = location.id
        row.is_pending = False
        row.updated_at = now

    session.commit()
    return len(rows)


def list_pending_rows(session: Session, user_id: int) -> list[InventoryRow]:
    rows = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card), joinedload(InventoryRow.storage_location))
        .filter(InventoryRow.is_pending.is_(True), InventoryRow.user_id == user_id)
        .all()
    )
    rows.sort(key=lambda r: (assign_drawer(r.card, r.finish), drawer_sort_key(r)))
    return rows


def _get_or_create_drawer_location(session: Session, user_id: int, drawer: str) -> StorageLocation:
    location = (
        session.query(StorageLocation)
        .filter(
            StorageLocation.user_id == user_id,
            StorageLocation.name == f"Drawer {drawer}",
            StorageLocation.type == "drawer",
        )
        .one_or_none()
    )
    if location is None:
        location = StorageLocation(
            user_id=user_id,
            name=f"Drawer {drawer}",
            type="drawer",
            parent_id=None,
            sort_order=int(drawer) if drawer.isdigit() else 0,
        )
        session.add(location)
        session.flush()
    return location


def confirm_pending_row(
    session: Session, row_id: int, user_id: int, location_id: int | None = None
) -> InventoryRow | None:
    row = (
        session.query(InventoryRow)
        .filter(InventoryRow.id == row_id, InventoryRow.user_id == user_id)
        .first()
    )

    if not row:
        return None

    if not row.is_pending:
        return row

    if location_id is not None:
        location = (
            session.query(StorageLocation)
            .filter(StorageLocation.id == location_id, StorageLocation.user_id == user_id)
            .one_or_none()
        )
        if location is None:
            raise ValueError("Storage location not found.")
    else:
        if not row.drawer or not row.slot:
            raise ValueError("Pending row has no assigned drawer/slot yet.")
        location = _get_or_create_drawer_location(session, user_id, row.drawer)

    row.storage_location_id = location.id
    row.is_pending = False
    row.updated_at = datetime.utcnow()

    if row.drawer:
        dest = f"drawer={row.drawer} slot={row.slot or '-'}"
    else:
        dest = location.name

    log_transaction(
        session=session,
        user_id=user_id,
        event_type="placement_confirmed",
        card_id=row.card_id,
        finish=row.finish,
        quantity_delta=0,
        source_location="pending",
        destination_location=dest,
        inventory_row_id=row.id,
        note="Pending row confirmed as placed",
    )
    session.commit()
    return row


def confirm_all_pending(session: Session, user_id: int) -> int:
    rows = (
        session.query(InventoryRow)
        .filter(InventoryRow.is_pending.is_(True), InventoryRow.user_id == user_id)
        .all()
    )
    count = 0
    now = datetime.utcnow()

    for row in rows:
        if not row.drawer or not row.slot:
            continue

        location = _get_or_create_drawer_location(session, user_id, row.drawer)

        row.storage_location_id = location.id
        row.is_pending = False
        row.updated_at = now

        log_transaction(
            session=session,
            user_id=user_id,
            event_type="placement_confirmed",
            card_id=row.card_id,
            finish=row.finish,
            quantity_delta=0,
            source_location="pending",
            destination_location=f"drawer={row.drawer or '-'} slot={row.slot or '-'}",
            inventory_row_id=row.id,
            note="Pending row confirmed as placed",
            flush=False,
        )
        count += 1

    session.commit()
    return count


def adjust_inventory_row_quantity(
    session: Session,
    row_id: int,
    user_id: int,
    quantity: int,
    event_type: str,
    note: str | None = None,
) -> InventoryRow | None:
    valid_event_types = {"remove", "sold", "traded", "row_deleted"}
    if event_type not in valid_event_types:
        raise ValueError(f"Unsupported event_type: {event_type}")

    row = (
        session.query(InventoryRow)
        .filter(InventoryRow.id == row_id, InventoryRow.user_id == user_id)
        .first()
    )

    if not row:
        raise ValueError("Inventory row not found.")
    if quantity <= 0:
        raise ValueError("Quantity must be at least 1.")
    if quantity > row.quantity:
        raise ValueError("Cannot remove more than the row quantity.")

    source_location = (
        "pending" if row.is_pending else f"drawer={row.drawer or '-'} slot={row.slot or '-'}"
    )

    log_transaction(
        session=session,
        user_id=user_id,
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
        session.commit()
        return None

    row.quantity -= quantity
    row.updated_at = datetime.utcnow()

    session.commit()
    return row


def delete_inventory_row(session: Session, row_id: int, user_id: int) -> bool:
    row = (
        session.query(InventoryRow)
        .filter(InventoryRow.id == row_id, InventoryRow.user_id == user_id)
        .first()
    )

    if not row:
        return False

    adjust_inventory_row_quantity(
        session=session,
        row_id=row_id,
        user_id=user_id,
        quantity=row.quantity,
        event_type="row_deleted",
        note=f"Deleted inventory row {row_id}",
    )

    return True


def undo_last_import(session: Session, user_id: int) -> bool:
    last_import = (
        session.query(TransactionLog)
        .filter(
            TransactionLog.user_id == user_id,
            TransactionLog.event_type == "import",
        )
        .order_by(TransactionLog.id.desc())
        .first()
    )
    if not last_import or not last_import.inventory_row_id:
        return False

    row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.id == last_import.inventory_row_id,
            InventoryRow.user_id == user_id,
        )
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
        user_id=user_id,
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


def undo_last_batch(session: Session, batch_id: int, user_id: int) -> int:
    logs = (
        session.query(TransactionLog)
        .filter(
            TransactionLog.user_id == user_id,
            TransactionLog.batch_id == batch_id,
            TransactionLog.event_type == "import",
        )
        .order_by(TransactionLog.id.desc())
        .all()
    )

    undone = 0
    for log in logs:
        row = (
            session.query(InventoryRow)
            .filter(
                InventoryRow.id == log.inventory_row_id,
                InventoryRow.user_id == user_id,
            )
            .first()
        )
        if row:
            row.quantity -= abs(log.quantity_delta)
            row.updated_at = datetime.utcnow()
            if row.quantity <= 0:
                session.delete(row)

        log_transaction(
            session=session,
            user_id=user_id,
            event_type="undo_batch_import",
            card_id=log.card_id,
            finish=log.finish,
            quantity_delta=-abs(log.quantity_delta),
            batch_id=log.batch_id,
            inventory_row_id=log.inventory_row_id,
            note=f"Undid import log {log.id} from batch {batch_id}",
            flush=False,
        )
        undone += 1

    session.commit()
    return undone


def get_previous_location_for_row(session: Session, row_id: int, user_id: int) -> str | None:
    log = (
        session.query(TransactionLog)
        .filter(
            TransactionLog.user_id == user_id,
            TransactionLog.inventory_row_id == row_id,
            TransactionLog.event_type == "resort",
            TransactionLog.source_location.isnot(None),
        )
        .order_by(TransactionLog.created_at.desc(), TransactionLog.id.desc())
        .first()
    )

    if not log or log.source_location == "pending":
        return None

    return log.source_location


def resort_collection(
    session: Session,
    user_id: int,
    row_ids: Iterable[int] | None = None,
) -> int:
    query = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card))
        .filter(InventoryRow.user_id == user_id)
    )

    if row_ids is not None:
        query = query.filter(InventoryRow.id.in_(list(row_ids)))

    rows = query.all()

    if not rows:
        return 0

    rows.sort(key=lambda r: (assign_drawer(r.card, r.finish), drawer_sort_key(r)))

    grouped: dict[int, list[InventoryRow]] = {i: [] for i in range(1, 7)}
    for row in rows:
        grouped[assign_drawer(row.card, row.finish)].append(row)

    updated = 0
    now = datetime.utcnow()

    for drawer_number, drawer_rows in grouped.items():
        location = (
            session.query(StorageLocation)
            .filter(
                StorageLocation.user_id == user_id,
                StorageLocation.name == f"Drawer {drawer_number}",
                StorageLocation.type == "drawer",
            )
            .one_or_none()
        )

        for index, row in enumerate(drawer_rows, start=1):
            target_drawer = str(drawer_number)
            target_slot = str(index)

            if row.drawer != target_drawer or row.slot != target_slot:
                old_drawer = row.drawer
                old_slot = row.slot
                old_is_pending = row.is_pending
                old_location = (
                    "pending"
                    if old_is_pending
                    else f"drawer={old_drawer or '-'} slot={old_slot or '-'}"
                )

                moved_between_drawers = (
                    not old_is_pending and old_drawer is not None and old_drawer != target_drawer
                )

                row.drawer = target_drawer
                row.slot = target_slot
                row.storage_location_id = location.id if location else None

                if old_is_pending:
                    row.is_pending = True
                elif old_drawer != target_drawer:
                    row.is_pending = True
                else:
                    row.is_pending = False

                row.updated_at = now

                log_transaction(
                    session=session,
                    user_id=user_id,
                    event_type="resort",
                    card_id=row.card_id,
                    finish=row.finish,
                    quantity_delta=0,
                    source_location=old_location,
                    destination_location=f"drawer={target_drawer} slot={target_slot}",
                    inventory_row_id=row.id,
                    note=(
                        "Auto-sorted collection row; moved to a new drawer and marked pending "
                        "for physical relocation"
                        if moved_between_drawers
                        else "Auto-sorted collection row by placement rules"
                    ),
                    flush=False,
                )
                updated += 1

    session.commit()
    return updated


def get_owned_cards_by_set(session: Session, set_code: str, user_id: int) -> dict[str, int]:
    rows = (
        session.query(InventoryRow)
        .join(Card)
        .filter(
            InventoryRow.user_id == user_id,
            Card.set_code == set_code.lower(),
        )
        .all()
    )

    owned: dict[str, int] = {}
    for row in rows:
        key = row.card.collector_number
        owned[key] = owned.get(key, 0) + row.quantity

    return owned


def list_owned_sets(session: Session, user_id: int) -> list[dict]:
    rows = (
        session.query(
            Card.set_code,
            func.max(Card.set_name),
            func.count(func.distinct(Card.collector_number)),
            func.sum(InventoryRow.quantity),
        )
        .join(InventoryRow, InventoryRow.card_id == Card.id)
        .filter(InventoryRow.user_id == user_id)
        .group_by(Card.set_code)
        .order_by(Card.set_code.asc())
        .all()
    )

    return [
        {
            "set_code": set_code,
            "set_name": set_name or set_code.upper(),
            "unique_owned": int(unique_owned or 0),
            "total_copies": int(total_copies or 0),
        }
        for set_code, set_name, unique_owned, total_copies in rows
    ]
