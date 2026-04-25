from __future__ import annotations

import math
import os

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import joinedload

from app.audit_service import list_transaction_logs
from app.db import get_session, init_db
from app.deck_service import (
    create_deck,
    get_deck,
    list_decks,
    pull_card_to_deck,
    return_card_from_deck,
)
from app.drawer_service import list_drawer_groups, list_rows_for_drawer
from app.import_service import normalize_finish, parse_scanner_csv, persist_import_rows
from app.inventory_service import (
    adjust_inventory_row_quantity,
    confirm_all_pending,
    confirm_pending_row,
    delete_inventory_row,
    get_drawer_label,
    get_inventory_row_stats,
    get_previous_location_for_row,
    is_price_stale,
    list_inventory_rows,
    list_pending_rows,
    resort_collection,
    undo_last_batch,
    undo_last_import,
    update_inventory_location,
)
from app.models import Card, ImportBatch, InventoryRow
from app.pricing import effective_price
from app.scryfall import (
    fetch_card_by_scryfall_id,
    fetch_card_by_set_and_number,
    refresh_card_from_scryfall,
)
from app.set_service import get_set_completion, list_set_completion_summaries

app = FastAPI(title="Mana Archive")

APP_VERSION = os.getenv("APP_VERSION", "dev")

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_version"] = APP_VERSION

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"request": request, "title": "Mana Archive"},
    )


@app.get("/import")
def import_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="import.html",
        context={"request": request, "title": "Import"},
    )


@app.post("/import/preview")
async def import_preview(request: Request, file: UploadFile = File(...)):
    file_bytes = await file.read()
    result = parse_scanner_csv(file_bytes)
    return templates.TemplateResponse(
        request=request,
        name="import_preview.html",
        context={
            "request": request,
            "title": "Import Preview",
            "valid_rows": result["valid_rows"],
            "invalid_rows": result["invalid_rows"],
            "filename": file.filename,
        },
    )


@app.post("/import/commit")
async def import_commit(
    request: Request,
    filename: str = Form("uploaded.csv"),
    line_number: list[str] = Form([]),
    name: list[str] = Form([]),
    scryfall_id: list[str] = Form([]),
    set_code: list[str] = Form([]),
    collector_number: list[str] = Form([]),
    finish: list[str] = Form([]),
    quantity: list[str] = Form([]),
    location: list[str] = Form([]),
):
    rows = []
    for i in range(len(line_number)):
        rows.append(
            {
                "line_number": int(line_number[i]),
                "name": name[i] if i < len(name) else "",
                "scryfall_id": scryfall_id[i],
                "set_code": set_code[i],
                "collector_number": collector_number[i],
                "finish": normalize_finish(finish[i]),
                "quantity": int(quantity[i]),
                "location": location[i],
            }
        )

    session = get_session()
    try:
        result = persist_import_rows(session, rows, filename=filename)

        if result.get("imported_row_ids"):
            resort_collection(session)
    finally:
        session.close()

    return RedirectResponse(url="/pending", status_code=303)


@app.post("/import/manual/preview")
async def manual_import_preview(
    request: Request,
    scryfall_id: str = Form(""),
    set_code: str = Form(""),
    collector_number: str = Form(""),
    finish: str = Form("normal"),
    quantity: int = Form(1),
):
    card = None
    resolved_id = ""
    if scryfall_id.strip():
        resolved_id = scryfall_id.strip()
        card = fetch_card_by_scryfall_id(resolved_id)
    else:
        card = fetch_card_by_set_and_number(set_code, collector_number)
        if card:
            resolved_id = card["scryfall_id"]

    return templates.TemplateResponse(
        request=request,
        name="manual_preview.html",
        context={
            "request": request,
            "title": "Manual Import Preview",
            "card": card,
            "resolved_scryfall_id": resolved_id,
            "finish": normalize_finish(finish),
            "quantity": max(1, quantity),
            "set_code": set_code,
            "collector_number": collector_number,
        },
    )


@app.post("/import/manual/commit")
async def manual_import_commit(
    request: Request,
    scryfall_id: str = Form(""),
    set_code: str = Form(""),
    collector_number: str = Form(""),
    finish: str = Form("normal"),
    quantity: int = Form(1),
):
    session = get_session()
    resorted_count = 0
    try:
        result = persist_import_rows(
            session,
            [
                {
                    "line_number": 1,
                    "scryfall_id": scryfall_id,
                    "set_code": set_code,
                    "collector_number": collector_number,
                    "finish": normalize_finish(finish),
                    "quantity": max(1, quantity),
                    "location": "",
                    "name": "",
                }
            ],
            filename="manual import",
        )
        if result.get("imported_row_ids"):
            resorted_count = resort_collection(session)

    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="import_result.html",
        context={
            "request": request,
            "title": "Import Results",
            "imported_count": result["imported_count"],
            "failed_rows": result["failed_rows"],
            "batch_id": result["batch_id"],
            "resorted_count": resorted_count,
            "resort_skipped": False,
        },
    )


@app.post("/inventory/rows/{row_id}/remove")
def remove_inventory_row_action(
    request: Request,
    row_id: int,
    quantity: int = Form(...),
    note: str = Form(""),
):
    session = get_session()
    try:
        adjust_inventory_row_quantity(
            session=session,
            row_id=row_id,
            quantity=quantity,
            event_type="remove",
            note=note or None,
        )
        session.commit()
    finally:
        session.close()

    return RedirectResponse(url=request.headers.get("referer") or "/collection", status_code=303)


@app.post("/inventory/rows/{row_id}/sell")
def sell_inventory_row_action(
    request: Request,
    row_id: int,
    quantity: int = Form(...),
    note: str = Form(""),
):
    session = get_session()
    try:
        adjust_inventory_row_quantity(
            session=session,
            row_id=row_id,
            quantity=quantity,
            event_type="sold",
            note=note or None,
        )
        session.commit()
    finally:
        session.close()

    return RedirectResponse(url=request.headers.get("referer") or "/collection", status_code=303)


@app.post("/inventory/rows/{row_id}/trade")
def trade_inventory_row_action(
    request: Request,
    row_id: int,
    quantity: int = Form(...),
    note: str = Form(""),
):
    session = get_session()
    try:
        adjust_inventory_row_quantity(
            session=session,
            row_id=row_id,
            quantity=quantity,
            event_type="traded",
            note=note or None,
        )
        session.commit()
    finally:
        session.close()

    return RedirectResponse(url=request.headers.get("referer") or "/collection", status_code=303)


@app.post("/inventory/rows/{row_id}/delete")
def delete_inventory_row_action(
    request: Request,
    row_id: int,
    note: str = Form(""),
):
    session = get_session()
    try:
        row = session.query(InventoryRow).filter(InventoryRow.id == row_id).first()
        if row:
            adjust_inventory_row_quantity(
                session=session,
                row_id=row_id,
                quantity=row.quantity,
                event_type="row_deleted",
                note=note or f"Deleted inventory row {row_id}",
            )
            session.commit()
    finally:
        session.close()

    return RedirectResponse(url=request.headers.get("referer") or "/collection", status_code=303)


@app.get("/collection")
def collection_page(
    request: Request,
    search: str = "",
    finish: str = "",
    drawer: str = "",
    sort: str = "newest",
    direction: str = "desc",
    page: int = 1,
):
    session = get_session()
    per_page = 50

    try:
        inventory_rows, total_count = list_inventory_rows(
            session,
            search=search,
            finish=finish,
            drawer=drawer,
            sort=sort,
            direction=direction,
            page=page,
            per_page=per_page,
        )

        stats = get_inventory_row_stats(
            session,
            search=search,
            finish=finish,
            drawer=drawer,
        )

        items = []
        for row in inventory_rows:
            price = effective_price(row.card, row.finish)
            price_updated_at = getattr(row.card, "updated_at", None)
            is_stale = is_price_stale(price_updated_at)
            has_price = price is not None

            if has_price:
                display_price = price
                total = price * row.quantity
                price_status = "stale" if is_stale else "current"
            else:
                display_price = 0.0
                total = 0.0
                price_status = "unknown"

            items.append(
                {
                    "id": row.id,
                    "card": row.card,
                    "finish": row.finish,
                    "quantity": row.quantity,
                    "drawer": row.drawer,
                    "slot": row.slot,
                    "is_pending": row.is_pending,
                    "effective_price": display_price,
                    "has_price": has_price,
                    "price_status": price_status,
                    "price_updated_at": price_updated_at,
                    "total_value": total,
                    "drawer_label": get_drawer_label(row.drawer),
                }
            )
    finally:
        session.close()

    total_pages = max(1, math.ceil(total_count / per_page))

    return templates.TemplateResponse(
        request=request,
        name="collection.html",
        context={
            "request": request,
            "title": "Collection",
            "items": items,
            "search": search,
            "finish_filter": finish,
            "drawer_filter": drawer,
            "sort": sort,
            "direction": direction,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": total_pages,
            "total_value": stats["total_value"],
            "total_cards": stats["total_cards"],
            "unique_cards": stats["unique_cards"],
            "drawer_counts": stats["drawer_counts"],
            "unassigned_count": stats["unassigned_count"],
        },
    )


@app.post("/collection/update-location")
async def collection_update_location(
    row_id: int = Form(...), drawer: str = Form(""), slot: str = Form("")
):
    session = get_session()
    try:
        update_inventory_location(session, row_id=row_id, drawer=drawer, slot=slot)
    finally:
        session.close()
    return RedirectResponse(url="/collection", status_code=303)


@app.post("/collection/delete")
async def collection_delete(row_id: int = Form(...)):
    session = get_session()
    try:
        delete_inventory_row(session, row_id)
    finally:
        session.close()
    return RedirectResponse(url="/collection", status_code=303)


@app.post("/collection/resort")
async def collection_resort():
    session = get_session()
    try:
        resort_collection(session)
    finally:
        session.close()
    return RedirectResponse(url="/collection", status_code=303)


@app.post("/cards/refresh")
async def card_refresh(request: Request, card_id: int = Form(...)):
    session = get_session()
    try:
        refresh_card_from_scryfall(session, card_id)
    finally:
        session.close()
    return RedirectResponse(
        url=request.headers.get("referer") or "/collection",
        status_code=303,
    )


@app.get("/pending")
def pending_page(request: Request):
    session = get_session()
    try:
        rows = list_pending_rows(session)
        latest_batch = session.query(ImportBatch).order_by(ImportBatch.id.desc()).first()
        items = []
        grouped = {}
        total_copies = 0
        for row in rows:
            price = effective_price(row.card, row.finish)
            previous_location = get_previous_location_for_row(session, row.id)

            item = {
                "id": row.id,
                "card": row.card,
                "finish": row.finish,
                "quantity": row.quantity,
                "drawer": row.drawer,
                "slot": row.slot,
                "price": price,
                "drawer_label": get_drawer_label(row.drawer),
                "previous_location": previous_location,
            }
            items.append(item)
            total_copies += row.quantity
            grouped.setdefault(str(row.drawer or "-"), []).append(item)
        grouped_drawers = []
        for key in sorted(
            grouped.keys(), key=lambda x: (x == "-", int(x) if x.isdigit() else 999, x)
        ):
            grouped_drawers.append(
                {
                    "drawer": key,
                    "label": get_drawer_label(key),
                    "count": len(grouped[key]),
                    "entries": grouped[key],
                }
            )
    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="pending.html",
        context={
            "request": request,
            "title": "Pending Placement",
            "items": items,
            "grouped_drawers": grouped_drawers,
            "pending_count": len(items),
            "drawer_count": len(grouped_drawers),
            "total_copies": total_copies,
            "latest_batch_id": latest_batch.id if latest_batch else None,
        },
    )


@app.post("/pending/confirm")
async def pending_confirm(row_id: int = Form(...)):
    session = get_session()
    try:
        confirm_pending_row(session, row_id=row_id)
    finally:
        session.close()
    return RedirectResponse(url="/pending", status_code=303)


@app.post("/pending/confirm-all")
async def pending_confirm_all():
    session = get_session()
    try:
        confirm_all_pending(session)
    finally:
        session.close()
    return RedirectResponse(url="/pending", status_code=303)


@app.get("/drawers")
def drawers_page(request: Request):
    session = get_session()
    try:
        grouped = list_drawer_groups(session)
        drawer_summaries = []
        for drawer_name, rows in grouped.items():
            total_value = sum(effective_price(row.card, row.finish) * row.quantity for row in rows)
            drawer_summaries.append(
                {"drawer": drawer_name, "row_count": len(rows), "total_value": total_value}
            )
        drawer_summaries.sort(key=lambda d: d["drawer"])
    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="drawers.html",
        context={"request": request, "title": "Drawers", "drawer_summaries": drawer_summaries},
    )


@app.get("/drawers/{drawer}")
def drawer_detail_page(request: Request, drawer: str):
    session = get_session()
    try:
        rows = list_rows_for_drawer(session, drawer)
        items = []
        total_copies = 0
        total_value = 0.0
        for row in rows:
            price = effective_price(row.card, row.finish)
            total = price * row.quantity
            items.append(
                {
                    "id": row.id,
                    "card": row.card,
                    "finish": row.finish,
                    "quantity": row.quantity,
                    "slot": row.slot,
                    "is_pending": row.is_pending,
                    "effective_price": price,
                    "total_value": total,
                    "drawer_label": get_drawer_label(drawer),
                }
            )
            total_copies += row.quantity
            total_value += total
    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="drawer_detail.html",
        context={
            "request": request,
            "title": f"Drawer {drawer}",
            "drawer": drawer,
            "drawer_label": get_drawer_label(drawer),
            "items": items,
            "entry_count": len(items),
            "total_copies": total_copies,
            "total_value": total_value,
        },
    )


@app.get("/audit")
def audit_page(request: Request):
    session = get_session()
    try:
        logs = list_transaction_logs(session)
        batches = session.query(ImportBatch).order_by(ImportBatch.id.desc()).all()
    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={"request": request, "title": "Audit Log", "logs": logs, "batches": batches},
    )


@app.post("/imports/undo-last")
async def imports_undo_last():
    session = get_session()
    try:
        undo_last_import(session)
    finally:
        session.close()
    return RedirectResponse(url="/audit", status_code=303)


@app.post("/imports/undo-batch")
async def imports_undo_batch(batch_id: int = Form(...)):
    session = get_session()
    try:
        undo_last_batch(session, batch_id)
    finally:
        session.close()
    return RedirectResponse(url="/pending", status_code=303)


@app.get("/decks")
def decks_page(request: Request):
    session = get_session()
    try:
        decks = list_decks(session)
    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="decks.html",
        context={"request": request, "title": "Decks", "decks": decks},
    )


@app.post("/decks/create")
async def decks_create(name: str = Form(...), format_name: str = Form(""), notes: str = Form("")):
    session = get_session()
    try:
        create_deck(session, name=name, format_name=format_name, notes=notes)
    finally:
        session.close()
    return RedirectResponse(url="/decks", status_code=303)


@app.get("/decks/{deck_id}")
def deck_detail_page(request: Request, deck_id: int):
    session = get_session()
    try:
        deck = get_deck(session, deck_id)
        items = []
        deck_total_value = 0.0
        total_cards = 0
        if deck:
            for item in deck.items:
                price = effective_price(item.card, item.finish)
                total_value = price * item.quantity
                deck_total_value += total_value
                total_cards += item.quantity
                items.append(
                    {
                        "id": item.id,
                        "card": item.card,
                        "finish": item.finish,
                        "quantity": item.quantity,
                        "effective_price": price,
                        "total_value": total_value,
                    }
                )
    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="deck_detail.html",
        context={
            "request": request,
            "title": deck.name if deck else "Deck",
            "deck": deck,
            "items": items if deck else [],
            "deck_total_value": deck_total_value if deck else 0.0,
            "deck_total_cards": total_cards if deck else 0,
        },
    )


@app.post("/decks/pull")
async def decks_pull(
    inventory_row_id: int = Form(...), deck_id: int = Form(...), quantity: int = Form(...)
):
    session = get_session()
    try:
        pull_card_to_deck(
            session, deck_id=deck_id, inventory_row_id=inventory_row_id, quantity=quantity
        )
    finally:
        session.close()
    return RedirectResponse(url=f"/decks/{deck_id}", status_code=303)


@app.post("/decks/return")
async def decks_return(
    deck_id: int = Form(...),
    deck_item_id: int = Form(...),
    drawer: str = Form(""),
    slot: str = Form(""),
):
    session = get_session()
    try:
        return_card_from_deck(session, deck_item_id=deck_item_id, drawer=drawer, slot=slot)
    finally:
        session.close()
    return RedirectResponse(url=f"/decks/{deck_id}", status_code=303)


@app.get("/test-scryfall/{scryfall_id}")
def test_scryfall(scryfall_id: str):
    card = fetch_card_by_scryfall_id(scryfall_id)
    return {"card": card}


@app.get("/cards/{card_id}")
def card_detail_page(request: Request, card_id: int):
    session = get_session()
    try:
        target_card = session.query(Card).filter(Card.id == card_id).first()
        if target_card is None:
            return RedirectResponse(url="/collection", status_code=303)

        inventory_rows = (
            session.query(InventoryRow)
            .options(joinedload(InventoryRow.card))
            .filter(InventoryRow.card_id == card_id)
            .all()
        )

        card_rows = []
        total_copies = 0
        total_value = 0.0

        for row in inventory_rows:
            price = effective_price(target_card, row.finish)
            total = price * row.quantity
            card_rows.append(
                {
                    "id": row.id,
                    "finish": row.finish,
                    "quantity": row.quantity,
                    "drawer": row.drawer,
                    "slot": row.slot,
                    "is_pending": row.is_pending,
                    "effective_price": price,
                    "total_value": total,
                    "drawer_label": get_drawer_label(row.drawer),
                }
            )
            total_copies += row.quantity
            total_value += total
    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="card_detail.html",
        context={
            "request": request,
            "title": target_card.name,
            "card": target_card,
            "rows": card_rows,
            "total_copies": total_copies,
            "total_value": total_value,
        },
    )


@app.post("/cards/refresh-stale")
async def refresh_stale_cards(request: Request):
    session = get_session()
    try:
        stale_cards = session.query(Card).all()
        for card in stale_cards:
            if is_price_stale(card.updated_at):
                refresh_card_from_scryfall(session, card.id)
    finally:
        session.close()
    return RedirectResponse(
        url=request.headers.get("referer") or "/collection",
        status_code=303,
    )


@app.get("/sets")
def sets_page(request: Request):
    session = get_session()
    try:
        sets = list_set_completion_summaries(session)
    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="sets.html",
        context={
            "request": request,
            "title": "Sets",
            "sets": sets,
        },
    )


@app.get("/sets/{set_code}")
def set_detail_page(request: Request, set_code: str, view: str = "all"):
    session = get_session()
    try:
        data = get_set_completion(session, set_code, view=view)
    finally:
        session.close()

    return templates.TemplateResponse(
        request=request,
        name="set_detail.html",
        context={
            "request": request,
            "title": data["set_name"],
            "data": data,
        },
    )
