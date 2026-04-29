"""CSV/manual import parsing and persistence logic.

Important placement rule:
Imports do not assign drawer/slot positions directly. Imported rows are created as
pending with ``drawer=None`` and ``slot=None`` so placement can be calculated by
``resort_collection`` against the full collection. This avoids slot collisions
with existing rows already assigned in the drawers.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.audit_service import create_import_batch, log_transaction
from app.models import Card, InventoryRow
from app.scryfall import fetch_card_by_scryfall_id, fetch_card_by_set_and_number


def normalize_finish(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned in {"foil", "traditional foil"}:
        return "foil"
    if cleaned in {"etched", "foil etched", "etched foil"}:
        return "etched"
    return "normal"


HEADER_ALIASES = {
    "scryfallid": "scryfall_id",
    "scryfall_id": "scryfall_id",
    "setcode": "set_code",
    "set_code": "set_code",
    "set": "set_code",
    "collectornumber": "collector_number",
    "collector_number": "collector_number",
    "collector#": "collector_number",
    "finish": "finish",
    "quantity": "quantity",
    "qty": "quantity",
    "count": "quantity",
    "location": "location",
    "name": "name",
    "type": "type",
}


def normalize_header(value: str | None) -> str:
    cleaned = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    cleaned = cleaned.replace("__", "_")
    return HEADER_ALIASES.get(cleaned.replace("_", ""), HEADER_ALIASES.get(cleaned, cleaned))


def build_finish_warnings(card_data: dict | None, finish: str) -> list[str]:
    warnings: list[str] = []
    normalized_finish = (finish or "normal").strip().lower()

    if not card_data:
        return warnings

    normal_price = card_data.get("price_usd")
    foil_price = card_data.get("price_usd_foil")
    etched_price = card_data.get("price_usd_etched")

    if normalized_finish == "foil":
        if not foil_price and normal_price:
            warnings.append(
                "Selected finish is Foil, but foil pricing is missing while normal pricing exists. Check the scanned finish."
            )

    elif normalized_finish == "etched":
        if not etched_price and (foil_price or normal_price):
            warnings.append(
                "Selected finish is Etched, but etched pricing is missing. Check the scanned finish."
            )

    else:  # normal
        if not normal_price and (foil_price or etched_price):
            warnings.append(
                "Selected finish is Normal, but normal pricing is missing while foil/etched pricing exists. Check the scanned finish."
            )

    return warnings


def parse_scanner_csv(file_bytes: bytes) -> dict[str, list[dict[str, Any]]]:
    text = file_bytes.decode("utf-8-sig", errors="replace")
    stream = io.StringIO(text)
    reader = csv.DictReader(stream)

    valid_rows: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []

    for line_number, raw_row in enumerate(reader, start=2):
        row = {normalize_header(k): (v or "").strip() for k, v in raw_row.items()}
        scryfall_id = row.get("scryfall_id", "")
        set_code = row.get("set_code", "").lower()
        collector_number = row.get("collector_number", "")
        raw_finish = row.get("finish", "")
        finish = normalize_finish(raw_finish)
        location = row.get("location", "")
        quantity_raw = row.get("quantity", "1")
        name = row.get("name", "")
        card_type = row.get("type", "")

        try:
            quantity = max(1, int(quantity_raw or "1"))
        except ValueError:
            quantity = 1

        cleaned = {
            "line_number": line_number,
            "scryfall_id": scryfall_id,
            "set_code": set_code,
            "collector_number": collector_number,
            "finish": finish,
            "quantity": quantity,
            "location": location,
            "name": name,
            "type": card_type,
            "warnings": [],
        }

        if scryfall_id or (set_code and collector_number):
            card_data: dict[str, Any] | None = None

            try:
                if scryfall_id:
                    card_data = fetch_card_by_scryfall_id(scryfall_id)
                elif set_code and collector_number:
                    card_data = fetch_card_by_set_and_number(set_code, collector_number)
                    if card_data and not cleaned["scryfall_id"]:
                        cleaned["scryfall_id"] = card_data.get("scryfall_id", "")
            except Exception:
                card_data = None

            cleaned["warnings"] = build_finish_warnings(card_data, finish)  # raw_finish)

            if card_data:
                cleaned["name"] = card_data.get("name") or cleaned["name"]
                cleaned["set_code"] = card_data.get("set_code") or cleaned["set_code"]
                cleaned["collector_number"] = (
                    card_data.get("collector_number") or cleaned["collector_number"]
                )

            valid_rows.append(cleaned)
        else:
            cleaned["reason"] = "Missing Scryfall ID and set/collector fallback fields."
            invalid_rows.append(cleaned)

    return {"valid_rows": valid_rows, "invalid_rows": invalid_rows}


def persist_import_rows(
    session: Session,
    rows: list[dict[str, Any]],
    filename: str = "manual import",
    user_id: int | None = None,
) -> dict[str, Any]:
    if user_id is None:
        raise ValueError("user_id is required when importing rows")
    imported_count = 0
    failed_rows: list[dict[str, Any]] = []
    imported_row_ids: list[int] = []
    batch = create_import_batch(session, filename=filename, row_count=len(rows))
    now = datetime.utcnow()

    candidate_rows: list[dict[str, Any]] = []
    for row in rows:
        scryfall_id = (row.get("scryfall_id") or "").strip()
        if scryfall_id:
            row["_resolved_scryfall_id"] = scryfall_id
            candidate_rows.append(row)
            continue

        card_data = fetch_card_by_set_and_number(
            row.get("set_code", ""), row.get("collector_number", "")
        )
        if not card_data:
            failed_rows.append(
                {
                    "line_number": row.get("line_number"),
                    "reason": "Scryfall lookup failed by set/collector fallback.",
                }
            )
            continue

        row["_resolved_scryfall_id"] = card_data["scryfall_id"]
        row["_prefetched_card_data"] = card_data
        candidate_rows.append(row)

    if not candidate_rows:
        session.commit()
        return {
            "imported_count": 0,
            "failed_rows": failed_rows,
            "batch_id": batch.id,
            "imported_row_ids": [],
        }

    unique_ids = sorted(
        {row["_resolved_scryfall_id"] for row in candidate_rows if row.get("_resolved_scryfall_id")}
    )

    existing_cards = session.query(Card).filter(Card.scryfall_id.in_(unique_ids)).all()
    card_map: dict[str, Card] = {card.scryfall_id: card for card in existing_cards}

    new_cards: list[Card] = []
    for sid in unique_ids:
        if sid in card_map:
            continue

        payload = None
        for row in candidate_rows:
            if row.get("_resolved_scryfall_id") == sid and row.get("_prefetched_card_data"):
                payload = row["_prefetched_card_data"]
                break

        if payload is None:
            payload = fetch_card_by_scryfall_id(sid)

        if not payload:
            for row in candidate_rows:
                if row.get("_resolved_scryfall_id") == sid:
                    row["_failed"] = True
                    failed_rows.append(
                        {
                            "line_number": row.get("line_number"),
                            "reason": "Card lookup failed by Scryfall ID.",
                        }
                    )
            continue

        card = Card(**payload, updated_at=now)
        session.add(card)
        new_cards.append(card)

    if new_cards:
        session.flush()
        for card in new_cards:
            card_map[card.scryfall_id] = card

    candidate_rows = [row for row in candidate_rows if not row.get("_failed")]

    for card in existing_cards:
        prefetched = next(
            (
                r.get("_prefetched_card_data")
                for r in candidate_rows
                if r.get("_resolved_scryfall_id") == card.scryfall_id
                and r.get("_prefetched_card_data")
            ),
            None,
        )
        if prefetched:
            card.name = prefetched["name"]
            card.set_code = prefetched["set_code"]
            card.set_name = prefetched["set_name"]
            card.collector_number = prefetched["collector_number"]
            card.rarity = prefetched["rarity"]
            card.image_url = prefetched["image_url"]
            card.type_line = prefetched["type_line"]
            card.oracle_text = prefetched["oracle_text"]
            card.price_usd = prefetched["price_usd"]
            card.price_usd_foil = prefetched["price_usd_foil"]
            card.price_usd_etched = prefetched["price_usd_etched"]
            card.updated_at = now

    card_ids = sorted(
        {
            card_map[row["_resolved_scryfall_id"]].id
            for row in candidate_rows
            if row.get("_resolved_scryfall_id") in card_map
        }
    )

    existing_pending_rows: list[InventoryRow] = []
    if card_ids:
        existing_pending_rows = (
            session.query(InventoryRow)
            .filter(InventoryRow.card_id.in_(card_ids))
            .filter(InventoryRow.user_id == user_id)
            .filter(InventoryRow.drawer.is_(None))
            .filter(InventoryRow.slot.is_(None))
            .filter(InventoryRow.is_pending.is_(True))
            .all()
        )

    inventory_map: dict[tuple[int, str, str | None, str | None, bool], InventoryRow] = {
        (row.user_id, row.card_id, row.finish, row.drawer, row.slot, row.is_pending): row
        for row in existing_pending_rows
    }

    created_rows: list[InventoryRow] = []
    audit_payloads: list[dict[str, Any]] = []

    for row in candidate_rows:
        sid = row["_resolved_scryfall_id"]
        card = card_map.get(sid)
        if not card:
            failed_rows.append(
                {
                    "line_number": row.get("line_number"),
                    "reason": "Card creation failed after resolution.",
                }
            )
            continue

        qty = max(1, int(row.get("quantity") or 1))
        finish = (row.get("finish") or "normal").strip().lower()
        location_note = (row.get("location") or "").strip() or None

        key = (user_id, card.id, finish, None, None, True)
        target_row = inventory_map.get(key)

        if target_row:
            target_row.quantity += qty
            target_row.updated_at = now
            if location_note:
                target_row.notes = location_note
        else:
            target_row = InventoryRow(
                user_id=user_id,
                card_id=card.id,
                finish=finish,
                quantity=qty,
                drawer=None,
                slot=None,
                is_pending=True,
                notes=location_note,
                created_at=now,
                updated_at=now,
            )
            session.add(target_row)
            created_rows.append(target_row)
            inventory_map[key] = target_row

        imported_count += 1
        audit_payloads.append(
            {
                "card_id": card.id,
                "finish": finish,
                "quantity_delta": qty,
                "batch_id": batch.id,
                "inventory_row": target_row,
                "note": f"Imported from row {row.get('line_number')}",
            }
        )

    if created_rows:
        session.flush()

    for payload in audit_payloads:
        imported_row_ids.append(payload["inventory_row"].id)
        log_transaction(
            session=session,
            event_type="import",
            card_id=payload["card_id"],
            finish=payload["finish"],
            quantity_delta=payload["quantity_delta"],
            source_location=None,
            destination_location="pending",
            batch_id=payload["batch_id"],
            inventory_row_id=payload["inventory_row"].id,
            note=payload["note"],
            flush=False,
        )

    session.commit()
    return {
        "imported_count": imported_count,
        "failed_rows": failed_rows,
        "batch_id": batch.id,
        "imported_row_ids": imported_row_ids,
    }
