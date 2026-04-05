"""
Core inventory service: atomic imports, re-indexing, placement confirmation,
and deck-pull operations.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, select

from mana_archive.logging_config import get_logger
from mana_archive.models import (
    Card,
    Finish,
    Inventory,
    TransactionKind,
    TransactionLog,
)
from mana_archive.sorter import assign_drawer, sort_key_for_card

log = get_logger(__name__)

DECK_DRAWER = 0  # Logical drawer number used for cards pulled to a deck


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_or_create_card(session: Session, card_data: dict[str, Any]) -> Card:
    """
    Upsert a Card record from parsed Scryfall data.

    Returns the Card instance (already added to the session, not yet committed).
    """
    stmt = select(Card).where(Card.scryfall_id == card_data["scryfall_id"])
    card = session.exec(stmt).first()

    if card is None:
        card = Card(**card_data, updated_at=datetime.utcnow())
        session.add(card)
        log.debug("Creating new card record: %s", card_data["name"])
    else:
        for key, value in card_data.items():
            setattr(card, key, value)
        card.updated_at = datetime.utcnow()
        log.debug("Updating existing card record: %s", card_data["name"])

    return card


def _next_position_in_drawer(session: Session, drawer: int) -> int:
    """Return the next available 1-based position at the end of a drawer."""
    stmt = select(Inventory).where(Inventory.drawer == drawer)
    existing = session.exec(stmt).all()
    return len(existing) + 1


def _reindex_drawer(session: Session, drawer: int) -> None:
    """
    Re-sort all cards in *drawer* alphabetically and reassign positions 1..N.

    This is called after any insert or removal so position numbers always
    reflect the physical alphabetical ordering in the drawer.
    """
    stmt = (
        select(Inventory, Card)
        .join(Card, Inventory.card_id == Card.id)
        .where(Inventory.drawer == drawer)
    )
    rows = list(session.exec(stmt).all())

    if not rows:
        return

    # Sort by set code then collector number; rows are (Inventory, Card) tuples
    rows.sort(key=lambda row: sort_key_for_card(row[1].set_code, row[1].collector_number))

    for idx, (entry, card) in enumerate(rows, start=1):
        if entry.position != idx:
            log.debug(
                "Reindex drawer=%d: '%s' %d -> %d",
                drawer,
                card.name,
                entry.position,
                idx,
            )
            entry.position = idx
            session.add(entry)


def _insert_with_reindex(session: Session, inventory: Inventory) -> None:
    """
    Insert an Inventory record into its drawer at the alphabetically correct
    position, then reindex the whole drawer to keep positions contiguous.
    """
    session.add(inventory)
    session.flush()  # persist so it appears in the reindex query
    _reindex_drawer(session, inventory.drawer)


def _nullify_tx_refs(session: Session, inventory_id: int) -> None:
    """
    Set TransactionLog.inventory_id = NULL for all rows referencing the given
    inventory_id. Must be called before session.delete() on an Inventory row to
    satisfy the FK constraint (SQLite does not support ON DELETE SET NULL natively
    without additional column flags).
    """
    stmt = (
        update(TransactionLog)
        .where(TransactionLog.inventory_id == inventory_id)
        .values(inventory_id=None)
    )
    session.exec(stmt)  # type: ignore[arg-type]


def _log_transaction(
    session: Session,
    *,
    card_id: int,
    inventory_id: int | None,
    kind: TransactionKind,
    detail: str = "",
    old_drawer: int | None = None,
    new_drawer: int | None = None,
    old_position: int | None = None,
    new_position: int | None = None,
    quantity_delta: int | None = None,
    batch_id: str | None = None,
) -> TransactionLog:
    tx = TransactionLog(
        card_id=card_id,
        inventory_id=inventory_id,
        kind=kind,
        detail=detail,
        old_drawer=old_drawer,
        new_drawer=new_drawer,
        old_position=old_position,
        new_position=new_position,
        quantity_delta=quantity_delta,
        batch_id=batch_id,
    )
    session.add(tx)
    return tx


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def import_single_card(
    session: Session,
    card_data: dict[str, Any],
    finish: Finish = Finish.NONFOIL,
    quantity: int = 1,
    batch_id: str | None = None,
) -> tuple[Inventory, TransactionLog]:
    """
    Atomically import one card into the inventory.

    1. Upsert the Card metadata record.
    2. Calculate the target drawer using the Sorter.
    3. Find or create an Inventory entry (same card + drawer + finish).
    4. Set is_placed=False (pending confirmation).
    5. Re-index the drawer.
    6. Write a TransactionLog entry.

    This entire operation should be called inside a database session; the
    caller is responsible for committing (or rolling back) the transaction.
    """
    card = _get_or_create_card(session, card_data)
    session.flush()  # ensure card.id is populated

    price = (
        card_data.get("price_usd_foil")
        if finish != Finish.NONFOIL
        else card_data.get("price_usd")
    )
    target_drawer = assign_drawer(card.set_code, price)

    # Check if an inventory entry already exists for this card/drawer/finish
    stmt = (
        select(Inventory)
        .where(Inventory.card_id == card.id)
        .where(Inventory.drawer == target_drawer)
        .where(Inventory.finish == finish)
        .where(Inventory.location_tag.is_(None))
    )
    inventory = session.exec(stmt).first()

    if inventory is None:
        inventory = Inventory(
            card_id=card.id,
            drawer=target_drawer,
            position=0,  # will be set by reindex
            quantity=quantity,
            finish=finish,
            is_placed=False,
        )
        _insert_with_reindex(session, inventory)
        log.info(
            "Imported '%s' into drawer %d (new entry, qty=%d).",
            card.name,
            target_drawer,
            quantity,
        )
    else:
        old_qty = inventory.quantity
        inventory.quantity += quantity
        inventory.is_placed = False  # require re-confirmation if quantity changes
        session.add(inventory)
        log.info(
            "Updated '%s' in drawer %d: qty %d -> %d.",
            card.name,
            target_drawer,
            old_qty,
            inventory.quantity,
        )

    tx = _log_transaction(
        session,
        card_id=card.id,
        inventory_id=inventory.id,
        kind=TransactionKind.IMPORT,
        detail=f"Imported {quantity}x {card.name} [{finish.value}] into drawer {target_drawer}",
        new_drawer=target_drawer,
        new_position=inventory.position,
        quantity_delta=quantity,
        batch_id=batch_id,
    )

    return inventory, tx


def import_from_csv(
    session: Session,
    csv_content: str,
    scryfall_fetch_fn,
    progress_callback=None,
) -> list[dict[str, Any]]:
    """
    Parse a CSV and import each row atomically (within the passed session).

    Expected CSV columns (case-insensitive):
      - name          : Card name (required if no scryfall_id)
      - scryfall_id   : Scryfall UUID (preferred)
      - set           : Set code (optional, helps name lookups)
      - quantity      : Defaults to 1
      - finish        : "foil" | "etched" | "nonfoil" (defaults to nonfoil)

    Parameters
    ----------
    session           : Active SQLModel session (caller commits/rolls back).
    csv_content       : Raw CSV text.
    scryfall_fetch_fn : Callable that accepts identifier dict and returns
                        parsed card_data dict or None.
    progress_callback : Optional callable(current, total, card_name) for UI.

    Returns
    -------
    list of dicts with keys: name, status ("ok" | "error"), detail.
    """
    from mana_archive.justtcg import fetch_prices_by_scryfall_ids, merge_prices_into_card_data

    batch_id = str(uuid.uuid4())
    reader = csv.DictReader(io.StringIO(csv_content))
    rows = list(reader)
    results: list[dict[str, Any]] = []
    total = len(rows)
    to_import: list[tuple[dict, Finish, int, str]] = []

    # Phase 1: fetch from Scryfall, collect successful rows
    for idx, row in enumerate(rows):
        row = {
            k.strip().lower().replace(" ", "_").replace("-", "_"): v.strip()
            for k, v in row.items()
        }

        scryfall_id = row.get("scryfall_id", "").strip()
        name = row.get("name", "").strip()
        set_code = row.get("set_code", row.get("set", "")).strip() or None

        try:
            quantity = max(1, int(row.get("quantity", 1)))
        except (ValueError, TypeError):
            quantity = 1

        raw_finish = row.get("finish", "nonfoil").lower()
        try:
            finish = Finish(raw_finish)
        except ValueError:
            finish = Finish.NONFOIL

        identifier = {}
        if scryfall_id:
            identifier = {"id": scryfall_id}
        elif name:
            identifier = {"name": name, "set": set_code} if set_code else {"name": name}
        else:
            results.append({"name": "(unknown)", "status": "error", "detail": "No name or scryfall_id"})
            continue

        display_name = name or scryfall_id

        if progress_callback:
            progress_callback(idx + 1, total, display_name)

        card_data = scryfall_fetch_fn(identifier)
        if card_data is None:
            log.warning("Scryfall lookup failed for %s, skipping.", display_name)
            results.append(
                {"name": display_name, "status": "error", "detail": "Scryfall lookup failed"}
            )
            continue

        to_import.append((card_data, finish, quantity, display_name))

    # Phase 2: batch fetch JustTCG prices and merge
    if to_import:
        ids = [t[0]["scryfall_id"] for t in to_import]
        prices = fetch_prices_by_scryfall_ids(ids)
        for card_data, _fin, _qty, _name in to_import:
            merge_prices_into_card_data(card_data, prices)

    # Phase 3: import
    for card_data, finish, quantity, display_name in to_import:
        try:
            inventory, _tx = import_single_card(
                session, card_data, finish, quantity, batch_id=batch_id
            )
            inv_drawer = inventory.drawer
            inv_position = inventory.position
            results.append(
                {
                    "name": card_data["name"],
                    "status": "ok",
                    "detail": f"Drawer {inv_drawer}, pos {inv_position}",
                }
            )
        except Exception as exc:
            log.exception("Failed to import %s: %s", display_name, exc)
            results.append({"name": display_name, "status": "error", "detail": str(exc)})

    return results


def confirm_placement(session: Session, inventory_id: int) -> Inventory:
    """
    Mark a pending inventory entry as physically placed (is_placed=True).
    """
    stmt = select(Inventory).where(Inventory.id == inventory_id)
    inventory = session.exec(stmt).first()
    if inventory is None:
        raise ValueError(f"Inventory entry {inventory_id} not found.")

    if inventory.is_placed:
        log.info("Inventory %d is already placed, no change.", inventory_id)
        return inventory

    inventory.is_placed = True
    session.add(inventory)

    _log_transaction(
        session,
        card_id=inventory.card_id,
        inventory_id=inventory.id,
        kind=TransactionKind.PLACEMENT_CONFIRMED,
        detail=f"Confirmed placement in drawer {inventory.drawer}, pos {inventory.position}",
        new_drawer=inventory.drawer,
        new_position=inventory.position,
    )
    log.info("Placement confirmed for inventory id=%d.", inventory_id)
    return inventory


def confirm_all_pending(session: Session) -> int:
    """Confirm all pending entries. Returns the count confirmed."""
    stmt = select(Inventory).where(Inventory.is_placed == False)  # noqa: E712
    pending = session.exec(stmt).all()
    count = 0
    for inv in pending:
        confirm_placement(session, inv.id)
        count += 1
    return count


def pull_card_to_deck(
    session: Session,
    inventory_id: int,
    deck_name: str,
    quantity: int = 1,
) -> Inventory:
    """
    Move *quantity* copies of an inventory entry to a virtual "Deck" location.

    If the full quantity is pulled, the original inventory entry is deleted and
    the drawer is re-indexed. If only a partial quantity is pulled, the
    original entry's quantity is decremented and a new deck entry is created.
    """
    stmt = select(Inventory).where(Inventory.id == inventory_id)
    source = session.exec(stmt).first()
    if source is None:
        raise ValueError(f"Inventory entry {inventory_id} not found.")

    if quantity > source.quantity:
        raise ValueError(
            f"Cannot pull {quantity}x from entry with only {source.quantity} copies."
        )

    old_drawer = source.drawer
    old_position = source.position

    # Create (or update) the deck entry
    deck_tag = f"DECK:{deck_name}"
    deck_stmt = (
        select(Inventory)
        .where(Inventory.card_id == source.card_id)
        .where(Inventory.finish == source.finish)
        .where(Inventory.location_tag == deck_tag)
    )
    deck_entry = session.exec(deck_stmt).first()

    if deck_entry is None:
        deck_entry = Inventory(
            card_id=source.card_id,
            drawer=DECK_DRAWER,
            position=1,
            quantity=quantity,
            finish=source.finish,
            is_placed=True,
            location_tag=deck_tag,
        )
        session.add(deck_entry)
    else:
        deck_entry.quantity += quantity
        session.add(deck_entry)

    # Decrement or remove the source entry
    if quantity == source.quantity:
        _nullify_tx_refs(session, source.id)
        session.delete(source)
        session.flush()
        _reindex_drawer(session, old_drawer)
    else:
        source.quantity -= quantity
        session.add(source)

    session.flush()

    _log_transaction(
        session,
        card_id=source.card_id,
        inventory_id=deck_entry.id,
        kind=TransactionKind.PULL,
        detail=f"Pulled {quantity}x to deck '{deck_name}'",
        old_drawer=old_drawer,
        new_drawer=DECK_DRAWER,
        old_position=old_position,
        quantity_delta=-quantity,
    )
    log.info(
        "Pulled %dx card_id=%d from drawer %d to deck '%s'.",
        quantity,
        source.card_id,
        old_drawer,
        deck_name,
    )
    return deck_entry


def return_card_from_deck(
    session: Session,
    deck_inventory_id: int,
    quantity: int = 1,
) -> Inventory:
    """
    Return *quantity* copies of a deck entry back to the main collection.

    The card is re-sorted into the appropriate drawer and the drawer is
    re-indexed.
    """
    stmt = select(Inventory).where(Inventory.id == deck_inventory_id)
    deck_entry = session.exec(stmt).first()
    if deck_entry is None:
        raise ValueError(f"Deck inventory entry {deck_inventory_id} not found.")

    if quantity > deck_entry.quantity:
        raise ValueError(
            f"Cannot return {quantity}x from deck entry with only {deck_entry.quantity} copies."
        )

    card_stmt = select(Card).where(Card.id == deck_entry.card_id)
    card = session.exec(card_stmt).first()
    if card is None:
        raise ValueError(f"Card {deck_entry.card_id} not found.")

    price = (
        card.price_usd_foil
        if deck_entry.finish != Finish.NONFOIL
        else card.price_usd
    )
    target_drawer = assign_drawer(card.set_code, price)

    # Decrement or remove deck entry
    if quantity == deck_entry.quantity:
        _nullify_tx_refs(session, deck_entry.id)
        session.delete(deck_entry)
    else:
        deck_entry.quantity -= quantity
        session.add(deck_entry)

    session.flush()

    # Merge back into collection drawer
    col_stmt = (
        select(Inventory)
        .where(Inventory.card_id == card.id)
        .where(Inventory.drawer == target_drawer)
        .where(Inventory.finish == deck_entry.finish)
        .where(Inventory.location_tag.is_(None))
    )
    col_entry = session.exec(col_stmt).first()

    if col_entry is None:
        col_entry = Inventory(
            card_id=card.id,
            drawer=target_drawer,
            position=0,
            quantity=quantity,
            finish=deck_entry.finish,
            is_placed=False,
        )
        session.add(col_entry)
        session.flush()
        _reindex_drawer(session, target_drawer)
    else:
        col_entry.quantity += quantity
        col_entry.is_placed = False
        session.add(col_entry)

    _log_transaction(
        session,
        card_id=card.id,
        inventory_id=col_entry.id,
        kind=TransactionKind.MOVE,
        detail=f"Returned {quantity}x from deck to drawer {target_drawer}",
        old_drawer=DECK_DRAWER,
        new_drawer=target_drawer,
        new_position=col_entry.position,
        quantity_delta=quantity,
    )
    return col_entry


def move_card(
    session: Session,
    inventory_id: int,
    new_drawer: int,
    quantity: int | None = None,
) -> Inventory:
    """
    Manually move an inventory entry to a different drawer.

    Re-indexes both the source and destination drawers.
    """
    stmt = select(Inventory).where(Inventory.id == inventory_id)
    source = session.exec(stmt).first()
    if source is None:
        raise ValueError(f"Inventory entry {inventory_id} not found.")

    move_qty = quantity if quantity is not None else source.quantity
    old_drawer = source.drawer
    old_position = source.position

    if old_drawer == new_drawer:
        return source

    if move_qty == source.quantity:
        source.drawer = new_drawer
        source.is_placed = False
        session.add(source)
        session.flush()
        _reindex_drawer(session, old_drawer)
        _reindex_drawer(session, new_drawer)
        moved = source
    else:
        source.quantity -= move_qty
        session.add(source)
        moved = Inventory(
            card_id=source.card_id,
            drawer=new_drawer,
            position=0,
            quantity=move_qty,
            finish=source.finish,
            is_placed=False,
        )
        session.add(moved)
        session.flush()
        _reindex_drawer(session, new_drawer)

    _log_transaction(
        session,
        card_id=source.card_id,
        inventory_id=moved.id,
        kind=TransactionKind.MOVE,
        detail=f"Moved {move_qty}x from drawer {old_drawer} to drawer {new_drawer}",
        old_drawer=old_drawer,
        new_drawer=new_drawer,
        old_position=old_position,
        new_position=moved.position,
        quantity_delta=0,
    )
    return moved


def re_sort_collection(session: Session) -> dict[str, int]:
    """
    Re-evaluate the correct drawer for every non-deck inventory entry and move
    any that are in the wrong drawer.

    This is the migration path for collections imported under a previous sorting
    scheme.  Both source and destination drawers are re-indexed after all moves.

    Returns
    -------
    dict with keys:
        "moved"    – number of entries reassigned to a different drawer
        "unchanged"– number of entries already in the correct drawer
    """
    stmt = (
        select(Inventory, Card)
        .join(Card, Inventory.card_id == Card.id)
        .where(Inventory.drawer != DECK_DRAWER)
        .where(Inventory.location_tag.is_(None))
    )
    rows = list(session.exec(stmt).all())

    moved_count = 0
    unchanged_count = 0
    dirty_drawers: set[int] = set()

    for inv, card in rows:
        price = (
            card.price_usd_foil
            if inv.finish != Finish.NONFOIL
            else card.price_usd
        )
        correct_drawer = assign_drawer(card.set_code, price)

        if inv.drawer == correct_drawer:
            unchanged_count += 1
            continue

        log.info(
            "Re-sort: '%s' (%s) %s -> drawer %d => drawer %d",
            card.name,
            card.set_code,
            inv.finish.value,
            inv.drawer,
            correct_drawer,
        )

        old_drawer = inv.drawer
        inv.drawer = correct_drawer
        inv.is_placed = False  # require re-confirmation after a move
        session.add(inv)

        _log_transaction(
            session,
            card_id=card.id,
            inventory_id=inv.id,
            kind=TransactionKind.MOVE,
            detail=(
                f"Re-sorted from drawer {old_drawer} to drawer {correct_drawer} "
                f"({card.set_code} #{card.collector_number})"
            ),
            old_drawer=old_drawer,
            new_drawer=correct_drawer,
        )

        dirty_drawers.add(old_drawer)
        dirty_drawers.add(correct_drawer)
        moved_count += 1

    session.flush()

    for drawer in dirty_drawers:
        _reindex_drawer(session, drawer)

    log.info(
        "Re-sort complete: %d moved, %d unchanged.",
        moved_count,
        unchanged_count,
    )
    return {"moved": moved_count, "unchanged": unchanged_count}


def clear_unplaced(session: Session) -> int:
    """
    Delete all Inventory entries where is_placed=False (pending confirmation).

    Re-indexes every drawer that had entries removed.  Returns the number of
    entries deleted.
    """
    stmt = select(Inventory).where(Inventory.is_placed == False)  # noqa: E712
    entries = session.exec(stmt).all()

    if not entries:
        return 0

    dirty_drawers: set[int] = set()
    count = 0

    for inv in entries:
        dirty_drawers.add(inv.drawer)
        _nullify_tx_refs(session, inv.id)
        session.delete(inv)
        count += 1

    session.flush()

    for drawer in dirty_drawers:
        _reindex_drawer(session, drawer)

    log.info("Cleared %d unplaced inventory entries.", count)
    return count


def undo_last_import(session: Session) -> dict:
    """
    Reverse the most recent IMPORT transaction.

    Behaviour
    ---------
    * Finds the latest TransactionLog entry with kind=IMPORT.
    * Decrements the linked Inventory entry's quantity by the original
      quantity_delta.
    * If the quantity reaches zero the Inventory row is deleted and the
      drawer is re-indexed.
    * Logs a reversal QUANTITY_UPDATE transaction so the audit trail is intact.

    Returns
    -------
    dict with keys:
        "card_name"  – name of the reversed card
        "quantity"   – number of copies removed
        "drawer"     – drawer the card was in
        "deleted"    – True if the inventory row was fully removed
    """
    # Find the most recent import transaction that still has an inventory link
    tx_stmt = (
        select(TransactionLog)
        .where(TransactionLog.kind == TransactionKind.IMPORT)
        .where(TransactionLog.inventory_id.is_not(None))
        .order_by(TransactionLog.timestamp.desc())
        .limit(1)
    )
    tx = session.exec(tx_stmt).first()

    if tx is None:
        raise ValueError("No import transactions found to undo.")

    inv_stmt = select(Inventory).where(Inventory.id == tx.inventory_id)
    inventory = session.exec(inv_stmt).first()

    if inventory is None:
        raise ValueError(
            f"Inventory entry {tx.inventory_id} no longer exists "
            f"(may have already been removed)."
        )

    card_stmt = select(Card).where(Card.id == tx.card_id)
    card = session.exec(card_stmt).first()
    card_name = card.name if card else f"card_id={tx.card_id}"

    qty_to_remove = tx.quantity_delta or 1
    drawer = inventory.drawer
    deleted = False

    if inventory.quantity <= qty_to_remove:
        # Remove the entry entirely
        _nullify_tx_refs(session, inventory.id)
        session.delete(inventory)
        session.flush()
        _reindex_drawer(session, drawer)
        deleted = True
    else:
        inventory.quantity -= qty_to_remove
        session.add(inventory)

    # Nullify the original tx's inventory_id so it can't be undone twice
    tx.inventory_id = None
    session.add(tx)

    _log_transaction(
        session,
        card_id=tx.card_id,
        inventory_id=None,
        kind=TransactionKind.QUANTITY_UPDATE,
        detail=(
            f"Undo import: removed {qty_to_remove}x {card_name} "
            f"from drawer {drawer}"
        ),
        old_drawer=drawer,
        quantity_delta=-qty_to_remove,
    )

    log.info(
        "Undid last import: %dx '%s' from drawer %d (deleted=%s).",
        qty_to_remove,
        card_name,
        drawer,
        deleted,
    )
    return {
        "card_name": card_name,
        "quantity": qty_to_remove,
        "drawer": drawer,
        "deleted": deleted,
    }


def undo_last_batch(session: Session) -> dict:
    """
    Reverse all IMPORT transactions that belong to the most recent CSV batch.

    Strategy
    --------
    1. **Preferred** – find the most recent ``batch_id`` (UUID tagged on imports
       created after the batch-tracking feature was added) and collect every
       IMPORT transaction that shares it.
    2. **Fallback** – if no ``batch_id`` exists (data imported before the
       feature landed), find the most recent IMPORT timestamp and collect all
       IMPORT transactions whose timestamp falls within
       ``_BATCH_WINDOW_MINUTES`` of it.  This reliably captures a single CSV
       run without pulling in earlier unrelated imports.

    For each collected transaction:
    - Decrement the linked Inventory entry's quantity by ``quantity_delta``.
    - Delete the row if quantity reaches zero and re-index the drawer.
    - Nullify the original transaction's ``inventory_id`` to prevent
      double-undoing and write a QUANTITY_UPDATE audit entry.

    Returns
    -------
    dict with keys:
        "batch_id"    – UUID that was reversed, or "(legacy)" for fallback
        "cards"       – list of card names affected
        "removed"     – number of inventory rows deleted
        "updated"     – number of inventory rows decremented (qty > 0 remaining)
        "drawers"     – set of drawer numbers that were re-indexed
    """
    from datetime import timedelta

    _BATCH_WINDOW_MINUTES = 10

    # Step 1 – prefer a tagged batch_id
    latest_tagged_stmt = (
        select(TransactionLog)
        .where(TransactionLog.kind == TransactionKind.IMPORT)
        .where(TransactionLog.batch_id.is_not(None))
        .where(TransactionLog.inventory_id.is_not(None))
        .order_by(TransactionLog.timestamp.desc())
        .limit(1)
    )
    latest_tagged = session.exec(latest_tagged_stmt).first()

    # Step 2 – also find the most recent IMPORT of any kind (tagged or not)
    latest_any_stmt = (
        select(TransactionLog)
        .where(TransactionLog.kind == TransactionKind.IMPORT)
        .where(TransactionLog.inventory_id.is_not(None))
        .order_by(TransactionLog.timestamp.desc())
        .limit(1)
    )
    latest_any = session.exec(latest_any_stmt).first()

    if latest_any is None:
        raise ValueError("No import transactions found to undo.")

    use_batch_id = (
        latest_tagged is not None
        and latest_tagged.timestamp >= latest_any.timestamp
    )

    if use_batch_id:
        target_batch_id: str = latest_tagged.batch_id  # type: ignore[assignment]
        all_tx_stmt = (
            select(TransactionLog)
            .where(TransactionLog.batch_id == target_batch_id)
            .where(TransactionLog.kind == TransactionKind.IMPORT)
            .where(TransactionLog.inventory_id.is_not(None))
        )
        display_batch_id = target_batch_id
    else:
        # Fallback: group by timestamp proximity
        anchor = latest_any.timestamp
        window_start = anchor - timedelta(minutes=_BATCH_WINDOW_MINUTES)
        all_tx_stmt = (
            select(TransactionLog)
            .where(TransactionLog.kind == TransactionKind.IMPORT)
            .where(TransactionLog.inventory_id.is_not(None))
            .where(TransactionLog.timestamp >= window_start)
            .where(TransactionLog.timestamp <= anchor)
        )
        target_batch_id = "(legacy)"
        display_batch_id = f"(legacy – within {_BATCH_WINDOW_MINUTES} min of {anchor:%H:%M})"
        log.info(
            "No batch_id found; falling back to timestamp window %s – %s.",
            window_start,
            anchor,
        )

    batch_txns: list[TransactionLog] = list(session.exec(all_tx_stmt).all())

    affected_drawers: set[int] = set()
    removed = 0
    updated = 0
    card_names: list[str] = []

    for tx in batch_txns:
        inv_stmt = select(Inventory).where(Inventory.id == tx.inventory_id)
        inventory = session.exec(inv_stmt).first()
        if inventory is None:
            # Already gone – just nullify the tx reference
            tx.inventory_id = None
            session.add(tx)
            continue

        card_stmt = select(Card).where(Card.id == tx.card_id)
        card = session.exec(card_stmt).first()
        card_name = card.name if card else f"card_id={tx.card_id}"
        card_names.append(card_name)

        qty_to_remove = tx.quantity_delta or 1
        drawer = inventory.drawer
        affected_drawers.add(drawer)

        if inventory.quantity <= qty_to_remove:
            _nullify_tx_refs(session, inventory.id)
            session.delete(inventory)
            removed += 1
        else:
            inventory.quantity -= qty_to_remove
            session.add(inventory)
            updated += 1

        # Prevent double-undo
        tx.inventory_id = None
        session.add(tx)

        short_id = target_batch_id[:8] if target_batch_id != "(legacy)" else "legacy"
        _log_transaction(
            session,
            card_id=tx.card_id,
            inventory_id=None,
            kind=TransactionKind.QUANTITY_UPDATE,
            detail=(
                f"Undo batch {short_id}: removed {qty_to_remove}x "
                f"{card_name} from drawer {drawer}"
            ),
            old_drawer=drawer,
            quantity_delta=-qty_to_remove,
        )

    session.flush()

    # Re-index every affected drawer once all deletes are flushed
    for drawer in affected_drawers:
        _reindex_drawer(session, drawer)

    log.info(
        "Undid batch %s: %d removed, %d updated across drawers %s.",
        display_batch_id,
        removed,
        updated,
        affected_drawers,
    )
    return {
        "batch_id": display_batch_id,
        "cards": card_names,
        "removed": removed,
        "updated": updated,
        "drawers": affected_drawers,
    }


def refresh_card_metadata(
    session: Session,
    progress_callback=None,
    resort_inventory: bool = False,
) -> dict[str, int]:
    """
    Re-fetch prices for every Card record from JustTCG.

    Uses JustTCG for current market prices (updated every 6 hours). Requires
    JUSTTCG_API_KEY in the environment. If the key is missing, falls back to
    Scryfall for a full metadata refresh (prices, images, oracle text).

    Parameters
    ----------
    session           : Active SQLModel session.
    progress_callback : Optional callable(current, total, card_name) for UI.

    Returns
    -------
    dict with keys "updated", "failed", "total", and optionally drawer move
    counts when resort_inventory=True.
    """
    from mana_archive.justtcg import fetch_prices_by_scryfall_ids, _get_api_key
    from mana_archive.scryfall import fetch_by_scryfall_id, parse_card_data

    cards = list(session.exec(select(Card)).all())
    total = len(cards)
    updated = 0
    failed = 0

    if _get_api_key():
        # JustTCG path: batch fetch prices only
        ids = [c.scryfall_id for c in cards]
        prices = fetch_prices_by_scryfall_ids(ids)

        for idx, card in enumerate(cards):
            if progress_callback:
                progress_callback(idx + 1, total, card.name)
            if card.scryfall_id not in prices:
                continue
            p = prices[card.scryfall_id]
            if p.get("price_usd") is not None:
                card.price_usd = p["price_usd"]
            if p.get("price_usd_foil") is not None:
                card.price_usd_foil = p["price_usd_foil"]
            card.updated_at = datetime.utcnow()
            session.add(card)
            updated += 1

            if updated % 50 == 0:
                session.flush()

        failed = total - len(prices)
    else:
        # Fallback: Scryfall for full metadata
        for idx, card in enumerate(cards):
            if progress_callback:
                progress_callback(idx + 1, total, card.name)

            raw = fetch_by_scryfall_id(card.scryfall_id)
            if raw is None:
                log.warning("Scryfall refresh failed for %s (%s)", card.name, card.scryfall_id)
                failed += 1
                continue

            card_data = parse_card_data(raw)
            for key, value in card_data.items():
                setattr(card, key, value)
            card.updated_at = datetime.utcnow()
            session.add(card)
            updated += 1

            if updated % 50 == 0:
                session.flush()

    session.flush()
    result = {"updated": updated, "failed": failed, "total": total}
    if resort_inventory:
        resort_result = re_sort_collection(session)
        result.update({
            "moved": resort_result["moved"],
            "unchanged": resort_result["unchanged"],
        })

    log.info(
        "Metadata refresh complete: %d updated, %d failed out of %d total.",
        updated, failed, total,
    )
    return result


def reset_database(engine) -> None:
    """
    Drop and recreate all tables, wiping the entire database.

    This is irreversible.  Accepts the SQLAlchemy engine directly so it can be
    called outside of a session context.
    """
    from sqlmodel import SQLModel

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    log.warning("Database reset: all tables dropped and recreated.")
