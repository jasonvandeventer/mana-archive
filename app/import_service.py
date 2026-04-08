from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy.orm import Session

from app.audit_service import create_import_batch, log_transaction
from app.inventory_service import create_or_merge_inventory_row, get_or_create_card
from app.scryfall import fetch_card_by_set_and_number, fetch_card_by_scryfall_id


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
        finish = normalize_finish(row.get("finish"))
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
        }

        if scryfall_id or (set_code and collector_number):
            valid_rows.append(cleaned)
        else:
            cleaned["reason"] = "Missing Scryfall ID and set/collector fallback fields."
            invalid_rows.append(cleaned)

    return {"valid_rows": valid_rows, "invalid_rows": invalid_rows}



def persist_import_rows(session: Session, rows: list[dict[str, Any]], filename: str = "manual import") -> dict[str, Any]:
    imported_count = 0
    failed_rows: list[dict[str, Any]] = []
    imported_row_ids: list[int] = []
    batch = create_import_batch(session, filename=filename, row_count=len(rows))

    for row in rows:
        scryfall_id = (row.get("scryfall_id") or "").strip()
        card_data = None

        if scryfall_id:
            card_data = fetch_card_by_scryfall_id(scryfall_id)

        if not card_data:
            card_data = fetch_card_by_set_and_number(row.get("set_code", ""), row.get("collector_number", ""))
            if card_data:
                scryfall_id = card_data["scryfall_id"]

        if not card_data or not scryfall_id:
            failed_rows.append({
                "line_number": row.get("line_number"),
                "reason": "Scryfall lookup failed by ID and set/collector fallback.",
            })
            continue

        card = get_or_create_card(session, scryfall_id, card_data=card_data)
        if not card:
            failed_rows.append({
                "line_number": row.get("line_number"),
                "reason": "Card creation failed after Scryfall lookup.",
            })
            continue

        inv_row = create_or_merge_inventory_row(
            session=session,
            card_id=card.id,
            finish=row["finish"],
            quantity=int(row["quantity"]),
            drawer=None,
            slot=None,
            is_pending=True,
            notes=row.get("location") or None,
        )
        imported_row_ids.append(inv_row.id)
        imported_count += 1

        log_transaction(
            session=session,
            event_type="import",
            card_id=card.id,
            finish=row["finish"],
            quantity_delta=int(row["quantity"]),
            source_location=None,
            destination_location="pending",
            batch_id=batch.id,
            inventory_row_id=inv_row.id,
            note=f"Imported from row {row.get('line_number')}",
        )

    session.commit()
    return {"imported_count": imported_count, "failed_rows": failed_rows, "batch_id": batch.id, "imported_row_ids": imported_row_ids}
