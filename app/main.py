"""FastAPI route entrypoint for Mana Archive.

Routes are grouped by feature flow rather than alphabetically. User-owned
operations receive `current_user.id` at the route boundary and pass it into the
service layer.
"""

from __future__ import annotations

import math
import os

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.sessions import SessionMiddleware

from app.audit_service import list_transaction_logs
from app.auth import hash_password
from app.db import init_db
from app.deck_service import (
    create_deck,
    delete_deck,
    get_deck,
    list_decks,
    pull_card_to_deck,
    return_card_from_deck,
)
from app.dependencies import get_current_user, get_db_session
from app.drawer_service import list_drawer_groups, list_rows_for_drawer
from app.import_service import normalize_finish, parse_scanner_csv, persist_import_rows
from app.inventory_service import (
    adjust_inventory_row_quantity,
    confirm_all_pending,
    confirm_pending_row,
    delete_inventory_row,
    get_drawer_label,
    get_inventory_row_stats,
    get_location_label,
    is_price_stale,
    list_inventory_rows,
    list_owned_sets,
    list_pending_rows,
    resort_collection,
    undo_last_batch,
    undo_last_import,
    update_inventory_location,
)
from app.location_service import (
    create_location,
    get_location,
    get_location_summary,
    list_locations,
    list_rows_for_location,
)
from app.models import Card, ImportBatch, InventoryRow, User
from app.presentation_service import build_pending_view_model
from app.pricing import effective_price
from app.routes import auth
from app.scryfall import (
    fetch_card_by_scryfall_id,
    fetch_card_by_set_and_number,
    refresh_card_from_scryfall,
)
from app.set_service import get_set_completion

app = FastAPI(title="Mana Archive")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "dev-only-change-me"),
    same_site="lax",
    https_only=os.getenv("DEV_MODE", "false").lower() != "true",
)

app.include_router(auth.router)

APP_VERSION = os.getenv("APP_VERSION", "dev")

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_version"] = APP_VERSION

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def home(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "request": request,
            "title": "Mana Archive",
            "current_user": current_user,
        },
    )


@app.post("/register")
def register(
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_db_session),
):
    existing = session.query(User).filter(User.username == username).first()
    if existing:
        return RedirectResponse("/login?error=exists", status_code=303)

    user = User(
        username=username,
        password_hash=hash_password(password),
        is_active=True,
    )
    session.add(user)
    session.commit()

    return RedirectResponse("/login", status_code=303)


@app.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"request": request, "title": "Register"},
    )


# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------


@app.get("/import")
def import_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request=request,
        name="import.html",
        context={
            "request": request,
            "title": "Import",
            "current_user": current_user,
        },
    )


@app.post("/import/preview")
async def import_preview(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
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
            "current_user": current_user,
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
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
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

    result = persist_import_rows(
        session,
        rows,
        filename=filename,
        user_id=current_user.id,
    )

    if result.get("imported_row_ids"):
        resort_collection(session, user_id=current_user.id)

    return RedirectResponse(url="/pending", status_code=303)


@app.post("/import/manual/preview")
async def manual_import_preview(
    request: Request,
    scryfall_id: str = Form(""),
    set_code: str = Form(""),
    collector_number: str = Form(""),
    finish: str = Form("normal"),
    quantity: int = Form(1),
    current_user: User = Depends(get_current_user),
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
            "current_user": current_user,
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
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
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
        user_id=current_user.id,
    )

    resorted_count = 0
    if result.get("imported_row_ids"):
        resorted_count = resort_collection(session, user_id=current_user.id)

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
            "current_user": current_user,
        },
    )


# -----------------------------------------------------------------------------
# Inventory mutations
# -----------------------------------------------------------------------------


@app.post("/inventory/rows/{row_id}/remove")
def remove_inventory_row_action(
    request: Request,
    row_id: int,
    quantity: int = Form(...),
    note: str = Form(""),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    adjust_inventory_row_quantity(
        session=session,
        row_id=row_id,
        user_id=current_user.id,
        quantity=quantity,
        event_type="remove",
        note=note or None,
    )

    return RedirectResponse(url=request.headers.get("referer") or "/collection", status_code=303)


@app.post("/inventory/rows/{row_id}/sell")
def sell_inventory_row_action(
    request: Request,
    row_id: int,
    quantity: int = Form(...),
    note: str = Form(""),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    adjust_inventory_row_quantity(
        session=session,
        row_id=row_id,
        user_id=current_user.id,
        quantity=quantity,
        event_type="sold",
        note=note or None,
    )

    return RedirectResponse(url=request.headers.get("referer") or "/collection", status_code=303)


@app.post("/inventory/rows/{row_id}/trade")
def trade_inventory_row_action(
    request: Request,
    row_id: int,
    quantity: int = Form(...),
    note: str = Form(""),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    adjust_inventory_row_quantity(
        session=session,
        row_id=row_id,
        user_id=current_user.id,
        quantity=quantity,
        event_type="traded",
        note=note or None,
    )

    return RedirectResponse(url=request.headers.get("referer") or "/collection", status_code=303)


@app.post("/inventory/rows/{row_id}/delete")
def delete_inventory_row_action(
    request: Request,
    row_id: int,
    note: str = Form(""),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    delete_inventory_row(
        session=session,
        row_id=row_id,
        user_id=current_user.id,
    )

    return RedirectResponse(
        url=request.headers.get("referer") or "/collection",
        status_code=303,
    )


# -----------------------------------------------------------------------------
# Collection
# -----------------------------------------------------------------------------


@app.get("/collection")
def collection_page(
    request: Request,
    search: str = "",
    finish: str = "",
    location_id: int = 0,
    sort: str = "newest",
    direction: str = "desc",
    page: int = 1,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    per_page = 50

    drawer = ""

    selected_location = None

    if location_id:
        selected_location = get_location(
            session,
            location_id=location_id,
            user_id=current_user.id,
        )
    if selected_location and selected_location.type == "drawer":
        drawer = selected_location.name.replace("Drawer", "").strip()

    inventory_rows, total_count = list_inventory_rows(
        session,
        user_id=current_user.id,
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
        user_id=current_user.id,
        search=search,
        finish=finish,
        drawer=drawer,
    )

    location_counts = {}
    for drawer_number, count in stats["drawer_counts"].items():
        if count > 0:
            location_counts[f"Drawer {drawer_number}"] = count

    if stats["unassigned_count"] > 0:
        location_counts["Unassigned"] = stats["unassigned_count"]

    decks = list_decks(session, user_id=current_user.id)
    locations = list_locations(session, user_id=current_user.id)
    items = []

    for row in inventory_rows:
        price = effective_price(row.card, row.finish)
        price_updated_at = getattr(row.card, "updated_at", None)
        is_stale = is_price_stale(price_updated_at)
        has_price = price is not None
        location_label = row.storage_location.name if row.storage_location else "Unassigned"

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
                "drawer_label": get_location_label(row),
                "location_label": location_label,
            }
        )

    total_pages = max(1, math.ceil(total_count / per_page))
    show_onboarding = total_count == 0

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
            "location_counts": location_counts,
            "decks": decks,
            "locations": locations,
            "location_id": location_id,
            "current_user": current_user,
            "show_onboarding": show_onboarding,
        },
    )


@app.post("/collection/update-location")
async def collection_update_location(
    row_id: int = Form(...),
    drawer: str = Form(""),
    slot: str = Form(""),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    update_inventory_location(
        session,
        row_id=row_id,
        user_id=current_user.id,
        drawer=drawer,
        slot=slot,
    )

    return RedirectResponse(url="/collection", status_code=303)


@app.post("/collection/delete")
async def collection_delete(
    row_id: int = Form(...),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    delete_inventory_row(session, row_id=row_id, user_id=current_user.id)
    return RedirectResponse(url="/collection", status_code=303)


@app.post("/collection/resort")
async def collection_resort(
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    resort_collection(session, user_id=current_user.id)
    return RedirectResponse(url="/collection", status_code=303)


# -----------------------------------------------------------------------------
# Pending placement
# -----------------------------------------------------------------------------


@app.get("/pending")
def pending_page(
    request: Request,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    rows = list_pending_rows(session, user_id=current_user.id)

    latest_batch = (
        session.query(ImportBatch)
        .filter(ImportBatch.user_id == current_user.id)
        .order_by(ImportBatch.id.desc())
        .first()
    )

    view_model = build_pending_view_model(rows)

    return templates.TemplateResponse(
        request=request,
        name="pending.html",
        context={
            "request": request,
            "title": "Pending Placement",
            **view_model,
            "latest_batch_id": latest_batch.id if latest_batch else None,
            "current_user": current_user,
        },
    )


@app.post("/pending/confirm")
async def pending_confirm(
    row_id: int = Form(...),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    confirm_pending_row(session, row_id=row_id, user_id=current_user.id)
    return RedirectResponse(url="/pending", status_code=303)


@app.post("/pending/confirm-all")
async def pending_confirm_all(
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    confirm_all_pending(session, user_id=current_user.id)
    return RedirectResponse(url="/pending", status_code=303)


@app.post("/pending/{row_id}/remove")
def remove_pending_row(
    row_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.id == row_id,
            InventoryRow.is_pending,
            InventoryRow.user_id == current_user.id,
        )
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Pending row not found")

    session.delete(row)
    session.commit()

    return RedirectResponse(url="/pending", status_code=303)


# -----------------------------------------------------------------------------
# Storage Locations
# -----------------------------------------------------------------------------


@app.get("/locations")
def locations_page(
    request: Request,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):

    location_summaries = get_location_summary(session, user_id=current_user.id)
    locations = [summary["location"] for summary in location_summaries]

    parent_locations = [loc for loc in locations if loc.type in {"root", "box", "binder", "other"}]

    return templates.TemplateResponse(
        request=request,
        name="locations.html",
        context={
            "title": "Storage Locations",
            "locations": locations,
            "parent_locations": parent_locations,
            "location_types": ["drawer", "binder", "box", "deck", "other"],
            "location_summaries": location_summaries,
            "current_user": current_user,
        },
    )


@app.post("/locations")
def create_location_route(
    name: str = Form(...),
    type: str = Form("other"),
    parent_id: int | None = Form(None),
    sort_order: int = Form(0),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    if parent_id == 0:
        parent_id = None

    create_location(
        session,
        user_id=current_user.id,
        name=name,
        type=type,
        parent_id=parent_id,
        sort_order=sort_order,
    )
    return RedirectResponse("/locations", status_code=303)


@app.get("/locations/{location_id}")
def location_detail_page(
    request: Request,
    location_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    location = get_location(session, location_id=location_id, user_id=current_user.id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")

    rows = list_rows_for_location(
        session,
        user_id=current_user.id,
        location_id=location_id,
    )

    items = []
    total_value = 0.0
    total_quantity = 0

    for row in rows:
        price = effective_price(row.card, row.finish) or 0.0
        row_total = price * row.quantity
        total_value += row_total
        total_quantity += row.quantity

        items.append(
            {
                "id": row.id,
                "card": row.card,
                "finish": row.finish,
                "quantity": row.quantity,
                "slot": row.slot,
                "effective_price": price,
                "total_value": row_total,
                "is_pending": row.is_pending,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="location_detail.html",
        context={
            "request": request,
            "title": location.name,
            "location": location,
            "items": items,
            "total_quantity": total_quantity,
            "total_value": total_value,
            "current_user": current_user,
        },
    )


# -----------------------------------------------------------------------------
# Drawers
# -----------------------------------------------------------------------------


@app.get("/drawers")
def drawers_page(
    request: Request,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    grouped = list_drawer_groups(session, user_id=current_user.id)

    drawer_summaries = []
    for drawer_name, rows in grouped.items():
        total_value = sum(
            (effective_price(row.card, row.finish) or 0.0) * row.quantity for row in rows
        )
        drawer_summaries.append(
            {"drawer": drawer_name, "row_count": len(rows), "total_value": total_value}
        )

    drawer_summaries.sort(key=lambda d: d["drawer"])

    return templates.TemplateResponse(
        request=request,
        name="drawers.html",
        context={
            "request": request,
            "title": "Drawers",
            "drawer_summaries": drawer_summaries,
            "current_user": current_user,
        },
    )


@app.get("/drawers/{drawer}")
def drawer_detail_page(
    request: Request,
    drawer: str,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    rows = list_rows_for_drawer(session, drawer, user_id=current_user.id)

    items = []
    total_copies = 0
    total_value = 0.0

    for row in rows:
        price = effective_price(row.card, row.finish) or 0.0
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
            "current_user": current_user,
        },
    )


# -----------------------------------------------------------------------------
# Audit / import undo
# -----------------------------------------------------------------------------


@app.get("/audit")
def audit_page(
    request: Request,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    logs = list_transaction_logs(session, user_id=current_user.id)
    batches = (
        session.query(ImportBatch)
        .filter(ImportBatch.user_id == current_user.id)
        .order_by(ImportBatch.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={
            "request": request,
            "title": "Audit Log",
            "logs": logs,
            "batches": batches,
            "current_user": current_user,
        },
    )


@app.post("/imports/undo-last")
async def imports_undo_last(
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    undo_last_import(session, user_id=current_user.id)
    return RedirectResponse(url="/audit", status_code=303)


@app.post("/imports/undo-batch")
async def imports_undo_batch(
    batch_id: int = Form(...),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    undo_last_batch(session, batch_id=batch_id, user_id=current_user.id)
    return RedirectResponse(url="/pending", status_code=303)


# -----------------------------------------------------------------------------
# Decks
# -----------------------------------------------------------------------------


@app.get("/decks")
def decks_page(
    request: Request,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    decks = list_decks(session, user_id=current_user.id)
    show_onboarding = len(decks) == 0

    return templates.TemplateResponse(
        request=request,
        name="decks.html",
        context={
            "request": request,
            "title": "Decks",
            "decks": decks,
            "current_user": current_user,
            "show_onboarding": show_onboarding,
        },
    )


@app.post("/decks/create")
async def decks_create(
    name: str = Form(...),
    format_name: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    create_deck(
        session,
        user_id=current_user.id,
        name=name,
        format_name=format_name,
        notes=notes,
    )

    return RedirectResponse(url="/decks", status_code=303)


@app.get("/decks/{deck_id}")
def deck_detail_page(
    request: Request,
    deck_id: int,
    search: str = "",
    collection_search: str = "",
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    deck = get_deck(session, deck_id=deck_id, user_id=current_user.id)
    items = []
    collection_results = []
    deck_total_value = 0.0
    total_cards = 0

    if deck:
        normalized_search = search.strip().lower()

        deck_rows = (
            session.query(InventoryRow)
            .filter(
                InventoryRow.user_id == current_user.id,
                InventoryRow.storage_location_id == deck.storage_location_id,
            )
            .all()
        )

        for row in deck_rows:
            if normalized_search:
                name = (row.card.name or "").lower()
                type_line = (row.card.type_line or "").lower()
                oracle = (row.card.oracle_text or "").lower()

                if (
                    normalized_search not in name
                    and normalized_search not in type_line
                    and normalized_search not in oracle
                ):
                    continue

            price = effective_price(row.card, row.finish) or 0.0
            total_value = price * row.quantity
            deck_total_value += total_value
            total_cards += row.quantity
            items.append(
                {
                    "id": row.id,
                    "card": row.card,
                    "finish": row.finish,
                    "quantity": row.quantity,
                    "effective_price": price,
                    "total_value": total_value,
                }
            )

    if collection_search.strip():
        rows, _ = list_inventory_rows(
            session,
            user_id=current_user.id,
            search=collection_search,
            page=1,
            per_page=20,
        )

        for row in rows:
            price = effective_price(row.card, row.finish) or 0.0
            collection_results.append(
                {
                    "id": row.id,
                    "card": row.card,
                    "finish": row.finish,
                    "quantity": row.quantity,
                    "drawer": row.drawer,
                    "slot": row.slot,
                    "effective_price": price,
                }
            )

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
            "search": search,
            "collection_search": collection_search,
            "collection_results": collection_results if deck else [],
            "current_user": current_user,
        },
    )


@app.post("/decks/{deck_id}/delete")
async def decks_delete(
    deck_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    delete_deck(session, deck_id=deck_id, user_id=current_user.id)
    return RedirectResponse(url="/decks", status_code=303)


@app.post("/decks/pull")
async def decks_pull(
    inventory_row_id: int = Form(...),
    deck_id: int = Form(...),
    quantity: int = Form(...),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    pull_card_to_deck(
        session,
        user_id=current_user.id,
        deck_id=deck_id,
        inventory_row_id=inventory_row_id,
        quantity=quantity,
    )

    return RedirectResponse(url=f"/decks/{deck_id}", status_code=303)


@app.post("/decks/return")
async def decks_return(
    deck_id: int = Form(...),
    deck_row_id: int = Form(...),
    drawer: str = Form(""),
    slot: str = Form(""),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    return_card_from_deck(
        session,
        user_id=current_user.id,
        deck_row_id=deck_row_id,
        drawer=drawer,
        slot=slot,
    )

    resort_collection(session, user_id=current_user.id)

    return RedirectResponse(url=f"/decks/{deck_id}", status_code=303)


# -----------------------------------------------------------------------------
# Cards / pricing
# -----------------------------------------------------------------------------


@app.get("/test-scryfall/{scryfall_id}")
def test_scryfall(
    scryfall_id: str,
    current_user: User = Depends(get_current_user),
):
    card = fetch_card_by_scryfall_id(scryfall_id)
    return {"card": card}


@app.get("/cards/{card_id}")
def card_detail_page(
    request: Request,
    card_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    target_card = session.query(Card).filter(Card.id == card_id).first()
    if target_card is None:
        return RedirectResponse(url="/collection", status_code=303)

    inventory_rows = (
        session.query(InventoryRow)
        .options(
            joinedload(InventoryRow.card),
            joinedload(InventoryRow.storage_location),
        )
        .filter(
            InventoryRow.card_id == card_id,
            InventoryRow.user_id == current_user.id,
        )
        .all()
    )

    card_rows = []
    total_copies = 0
    total_value = 0.0

    for row in inventory_rows:
        price = effective_price(target_card, row.finish) or 0.0
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
                "drawer_label": get_location_label(row),
            }
        )
        total_copies += row.quantity
        total_value += total

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
            "current_user": current_user,
        },
    )


@app.post("/cards/refresh")
async def card_refresh(
    request: Request,
    card_id: int = Form(...),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    owned_row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.card_id == card_id,
            InventoryRow.user_id == current_user.id,
        )
        .first()
    )

    if owned_row is None:
        raise HTTPException(status_code=404, detail="Card not found in current user's collection")

    refresh_card_from_scryfall(session, card_id)

    return RedirectResponse(
        url=request.headers.get("referer") or "/collection",
        status_code=303,
    )


@app.post("/cards/refresh-stale")
async def refresh_stale_cards(
    request: Request,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    stale_cards = (
        session.query(Card)
        .join(InventoryRow, InventoryRow.card_id == Card.id)
        .filter(InventoryRow.user_id == current_user.id)
        .distinct()
        .all()
    )

    for card in stale_cards:
        if is_price_stale(card.updated_at):
            refresh_card_from_scryfall(session, card.id)

    return RedirectResponse(
        url=request.headers.get("referer") or "/collection",
        status_code=303,
    )


# -----------------------------------------------------------------------------
# Sets
# -----------------------------------------------------------------------------


@app.get("/sets")
def sets_page(
    request: Request,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    sets = list_owned_sets(session, user_id=current_user.id)

    return templates.TemplateResponse(
        request=request,
        name="sets.html",
        context={
            "request": request,
            "title": "Sets",
            "sets": sets,
            "current_user": current_user,
        },
    )


@app.get("/sets/{set_code}")
def set_detail_page(
    request: Request,
    set_code: str,
    view: str = "all",
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    data = get_set_completion(session, set_code, view=view, user_id=current_user.id)

    return templates.TemplateResponse(
        request=request,
        name="set_detail.html",
        context={
            "request": request,
            "title": data["set_name"],
            "data": data,
            "current_user": current_user,
        },
    )
