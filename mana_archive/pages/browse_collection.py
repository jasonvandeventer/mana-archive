"""Browse Collection page – search, filter, and explore the inventory."""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

import streamlit as st
from sqlalchemy import Integer, func
from sqlmodel import Session, select

from mana_archive.database import get_engine, get_session
from mana_archive.inventory_service import (
    clear_unplaced,
    re_sort_collection,
    refresh_card_metadata,
    reset_database,
)
from mana_archive.logging_config import get_logger
from mana_archive.models import Card, Inventory

log = get_logger(__name__)

DRAWER_LABELS = {
    0: "Deck",
    1: "Drawer 1 – Value ($5+)",
    2: "Drawer 2 – Sets A–D",
    3: "Drawer 3 – Sets E–L",
    4: "Drawer 4 – Sets M–R",
    5: "Drawer 5 – Sets S–Z",
    6: "Drawer 6 – Non-alpha sets (2x2, etc.)",
}

PAGE_SIZE = 48   # plenty of cards; the CSS grid decides how many columns fit
# Minimum card width in px – the browser adds more columns whenever the
# viewport is wide enough to fit another one at this size.
CARD_MIN_WIDTH = 220


# Maps UI label -> (SQLAlchemy column expression, secondary sort for ties)
_SORT_OPTIONS: dict[str, tuple] = {
    "Drawer / Position": (Inventory.drawer, Inventory.position),
    "Name":              (func.lower(Card.name), Inventory.drawer),
    "Set Code":          (func.lower(Card.set_code), Card.collector_number),
    "Price ↓":           (Card.price_usd.desc(), func.lower(Card.name)),  # type: ignore[attr-defined]
    "Price ↑":           (Card.price_usd, func.lower(Card.name)),
    "CMC":               (Card.cmc, func.lower(Card.name)),
    "Type":              (func.lower(Card.type_line), func.lower(Card.name)),
    "Quantity ↓":        (Inventory.quantity.desc(), func.lower(Card.name)),  # type: ignore[attr-defined]
}


def _query_inventory(
    search: str,
    drawers: list[int],
    min_price: float,
    max_price: float,
    placed_filter: str,
    sort_by: str,
    page: int,
) -> tuple[list[dict], int]:
    """Return (page_rows, total_count) for the given filters and sort order."""
    with Session(get_engine()) as session:
        base_stmt = (
            select(Inventory, Card)
            .join(Card, Inventory.card_id == Card.id)
            .where(Inventory.drawer != 0)  # exclude deck entries from browse
        )

        if search:
            base_stmt = base_stmt.where(
                func.lower(Card.name).contains(search.lower())
            )
        if drawers:
            base_stmt = base_stmt.where(Inventory.drawer.in_(drawers))
        if min_price > 0:
            base_stmt = base_stmt.where(Card.price_usd >= min_price)
        if max_price < 9999:
            base_stmt = base_stmt.where(Card.price_usd <= max_price)
        if placed_filter == "Placed only":
            base_stmt = base_stmt.where(Inventory.is_placed == True)  # noqa: E712
        elif placed_filter == "Pending only":
            base_stmt = base_stmt.where(Inventory.is_placed == False)  # noqa: E712

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = session.exec(count_stmt).one()

        primary, secondary = _SORT_OPTIONS.get(
            sort_by, (Inventory.drawer, Inventory.position)
        )
        page_stmt = (
            base_stmt
            .order_by(primary, secondary)
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
        rows = session.exec(page_stmt).all()

        result = []
        for inv, card in rows:
            result.append(
                {
                    "inv_id": inv.id,
                    "name": card.name,
                    "set_code": card.set_code,
                    "set_name": card.set_name,
                    "collector_number": card.collector_number,
                    "rarity": card.rarity,
                    "type_line": card.type_line,
                    "mana_cost": card.mana_cost,
                    "cmc": card.cmc,
                    "oracle_text": card.oracle_text,
                    "finish": inv.finish.value,
                    "drawer": inv.drawer,
                    "position": inv.position,
                    "quantity": inv.quantity,
                    "is_placed": inv.is_placed,
                    "price_usd": card.price_usd,
                    "price_usd_foil": card.price_usd_foil,
                    "colors": card.colors,
                    "image_uri": card.image_uri,
                    "scryfall_id": card.scryfall_id,
                    "price_source": card.price_source,
                    "price_last_updated_at": card.price_last_updated_at,
                    "updated_at": card.updated_at,
                }
            )
        return result, total


def _drawer_summary() -> dict[int, dict]:
    """Return per-drawer stats: card count, total copies, unplaced count."""
    with Session(get_engine()) as session:
        stmt = (
            select(
                Inventory.drawer,
                func.count(Inventory.id).label("card_entries"),
                func.sum(Inventory.quantity).label("total_copies"),
                func.sum(
                    func.cast(Inventory.is_placed == False, Integer)  # noqa: E712
                ).label("unplaced"),
            )
            .where(Inventory.drawer != 0)
            .group_by(Inventory.drawer)
        )
        rows = session.exec(stmt).all()
        summary = {}
        for row in rows:
            summary[row.drawer] = {
                "card_entries": row.card_entries,
                "total_copies": row.total_copies or 0,
                "unplaced": row.unplaced or 0,
            }
        return summary


def _collection_totals() -> dict:
    """Return aggregate stats for the whole collection (excluding decks)."""
    with Session(get_engine()) as session:
        stmt = (
            select(
                func.count(Inventory.id).label("entries"),
                func.sum(Inventory.quantity).label("total_copies"),
                func.sum(Card.price_usd * Inventory.quantity).label("total_value"),
            )
            .join(Card, Inventory.card_id == Card.id)
            .where(Inventory.drawer != 0)
            .where(Inventory.location_tag.is_(None))
        )
        row = session.exec(stmt).one()
        return {
            "entries": row.entries or 0,
            "total_copies": row.total_copies or 0,
            "total_value": float(row.total_value or 0),
        }


def render() -> None:
    st.header("Browse Collection")

    # ── Collection value banner ────────────────────────────────────────────
    totals = _collection_totals()
    summary = _drawer_summary()

    val_col, copies_col, entries_col, spacer = st.columns([3, 2, 2, 5])
    val_col.metric("Collection Value", f"${totals['total_value']:,.2f}")
    copies_col.metric("Total Copies", f"{totals['total_copies']:,}")
    entries_col.metric("Unique Entries", f"{totals['entries']:,}")

    st.divider()

    # ── Drawer overview ────────────────────────────────────────────────────
    if summary:
        drawer_cols = st.columns(6)
        for i, drawer_num in enumerate(range(1, 7)):
            data = summary.get(drawer_num, {"card_entries": 0, "total_copies": 0, "unplaced": 0})
            label = DRAWER_LABELS.get(drawer_num, f"Drawer {drawer_num}").split("–")[0].strip()
            with drawer_cols[i]:
                st.metric(label, data["total_copies"])
                if data["unplaced"]:
                    st.caption(f"⚠ {data['unplaced']} unplaced")

    st.divider()

    # ── Maintenance ────────────────────────────────────────────────────────
    with st.expander("🔧 Maintenance", expanded=False):

        st.markdown("#### Refresh Card Metadata")
        st.caption(
            "Refreshes cached prices only for cards with missing or stale pricing. "
            "Runs are capped to fit JustTCG free-tier limits and automatically "
            "re-sort cards after repricing."
        )
        if st.button("Refresh Metadata", key="btn_refresh_meta"):
            progress_bar = st.progress(0.0, text="Starting…")

            def _on_progress(current: int, total: int, card_name: str) -> None:
                frac = current / total if total else 1.0
                progress_bar.progress(frac, text=f"({current}/{total}) {card_name}")

            with get_session() as session:
                meta_result = refresh_card_metadata(session, progress_callback=_on_progress)

            progress_bar.empty()
            st.success(
                f"Refresh complete: **{meta_result['updated']}** updated, "
                f"**{meta_result['failed']}** failed out of "
                f"**{meta_result['total']}** targeted cards; "
                f"**{meta_result['skipped']}** fresh cards skipped; "
                f"**{meta_result['moved']}** cards re-sorted after repricing."
            )
            st.rerun()

        st.divider()

        st.markdown("#### Re-sort Collection")
        st.caption(
            "Recalculates the correct drawer for every card using the current "
            "sorting rules (set code + price) and moves any that are in the wrong "
            "drawer. Moved cards are marked as pending placement."
        )
        if st.button("Re-sort Collection", key="btn_resort", type="primary"):
            with get_session() as session:
                result = re_sort_collection(session)
            moved = result["moved"]
            unchanged = result["unchanged"]
            if moved:
                st.success(
                    f"Re-sort complete: **{moved}** card(s) moved to correct drawers, "
                    f"{unchanged} already correct."
                )
                st.rerun()
            else:
                st.info(f"All {unchanged} cards are already in the correct drawers.")

        st.divider()

        st.markdown("#### Clear Unplaced Cards")
        st.caption(
            "Removes all inventory entries that have not yet been confirmed as "
            "physically placed. Cards that were already confirmed are untouched."
        )
        confirm_unplaced = st.checkbox(
            "I understand this will permanently delete all pending entries",
            key="confirm_clear_unplaced",
        )
        if st.button(
            "Clear Unplaced Cards",
            key="btn_clear_unplaced",
            disabled=not confirm_unplaced,
        ):
            with get_session() as session:
                deleted = clear_unplaced(session)
            st.success(f"Removed **{deleted}** unplaced entr{'y' if deleted == 1 else 'ies'}.")
            st.rerun()

        st.divider()

        st.markdown("#### Reset Database")
        st.warning(
            "This will **permanently delete all cards, inventory, and logs**. "
            "There is no undo."
        )
        confirm_reset = st.checkbox(
            "I understand this will wipe the entire database",
            key="confirm_reset_db",
        )
        if st.button(
            "Reset Database",
            key="btn_reset_db",
            type="primary",
            disabled=not confirm_reset,
        ):
            reset_database(get_engine())
            st.success("Database has been reset. All data has been wiped.")
            st.rerun()

    # ── Filters ────────────────────────────────────────────────────────────
    with st.expander("Filters & Sort", expanded=True):
        row1_c1, row1_c2, row1_c3, row1_c4 = st.columns([3, 2, 2, 2])
        with row1_c1:
            search = st.text_input("Search by name", placeholder="Lightning…")
        with row1_c2:
            drawer_options = [f"Drawer {n}" for n in range(1, 7)]
            selected_drawers_str = st.multiselect("Drawers", drawer_options)
            selected_drawers = [int(s.split()[-1]) for s in selected_drawers_str]
        with row1_c3:
            price_range = st.slider("Price range ($)", 0.0, 500.0, (0.0, 9999.0), step=0.5)
        with row1_c4:
            placed_filter = st.selectbox(
                "Placement", ["All", "Placed only", "Pending only"]
            )

        row2_c1, row2_c2, _row2_spacer = st.columns([2, 2, 8])
        with row2_c1:
            sort_by = st.selectbox("Sort by", list(_SORT_OPTIONS.keys()))

    page = st.number_input("Page", min_value=1, value=1, step=1)

    rows, total = _query_inventory(
        search,
        selected_drawers,
        price_range[0],
        price_range[1] if price_range[1] < 500.0 else 9999,
        placed_filter,
        sort_by,
        page,
    )

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.caption(f"Page {page} of {total_pages}  ·  {total:,} total entries")

    if not rows:
        st.info("No cards match the current filters.")
        return

    # ── Responsive CSS-grid card gallery ──────────────────────────────────
    card_items_html = []
    stale_cutoff = datetime.utcnow() - timedelta(hours=24)

    for card in rows:
        placed_icon = "✅" if card["is_placed"] else "⏳"
        price_str = f"${card['price_usd']:.2f}" if card["price_usd"] is not None else "—"
        drawer_label = DRAWER_LABELS.get(card["drawer"], f"Drawer {card['drawer']}")

        name_html = escape(card["name"])
        set_name_html = escape(card["set_name"])
        set_code_html = escape(card["set_code"].upper())
        image_uri = escape(card["image_uri"]) if card["image_uri"] else None
        scryfall_url = f"https://scryfall.com/card/{card['set_code'].lower()}/{card['collector_number']}"

        price_updated = card.get("price_last_updated_at")
        price_source = escape((card.get("price_source") or "unknown").title())
        stale_badge = ""
        if card["price_usd"] is None and card["price_usd_foil"] is None:
            stale_badge = (
                '<span style="display:inline-block;margin-top:6px;padding:2px 8px;border-radius:999px;'
                'background:#4b2b2b;color:#ffb3b3;font-size:0.72rem;font-weight:600;">'
                'Price missing</span>'
            )
        elif price_updated is None or price_updated <= stale_cutoff:
            age_text = "Stale"
            if price_updated is not None:
                age = datetime.utcnow() - price_updated
                hours_old = max(1, int(age.total_seconds() // 3600))
                if hours_old >= 48:
                    age_text = f"Stale · {hours_old // 24}d old"
                else:
                    age_text = f"Stale · {hours_old}h old"
            stale_badge = (
                '<span style="display:inline-block;margin-top:6px;padding:2px 8px;border-radius:999px;'
                'background:#4a4020;color:#f3d27a;font-size:0.72rem;font-weight:600;">'
                f'{age_text}</span>'
            )

        if image_uri:
            img_html = (
                f'<img src="{image_uri}" '
                f'alt="{name_html}" '
                f'style="width:100%;border-radius:6px 6px 0 0;display:block;">'
            )
        else:
            img_html = (
                '<div style="width:100%;aspect-ratio:5/7;background:#2a2a2a;'
                'display:flex;align-items:center;justify-content:center;'
                'border-radius:6px 6px 0 0;color:#666;font-size:0.8rem;">'
                "No image</div>"
            )

        card_items_html.append(
            f"""
            <div style="
                background:#1e1e1e;
                border:1px solid #333;
                border-radius:8px;
                overflow:hidden;
                display:flex;
                flex-direction:column;
            ">
                {img_html}
                <div style="padding:8px 10px;font-size:0.78rem;line-height:1.5;color:#ddd;">
                    <div style="font-weight:600;font-size:0.85rem;color:#fff;margin-bottom:2px;">
                        {placed_icon} <a href="{scryfall_url}" target="_blank" rel="noopener noreferrer" style="color:#8ec5ff;text-decoration:none;">{name_html}</a>
                    </div>
                    <div style="color:#aaa;">
                        {set_name_html}&nbsp;&middot;&nbsp;
                        {set_code_html}&nbsp;#{card["position"]}
                    </div>
                    <div>
                        {card["finish"].capitalize()}&nbsp;&middot;&nbsp;
                        Qty&nbsp;{card["quantity"]}&nbsp;&middot;&nbsp;
                        <strong style="color:#e8c96a;">{price_str}</strong>
                    </div>
                    <div style="color:#888;margin-top:2px;">{drawer_label}</div>
                    <div style="color:#777;margin-top:2px;font-size:0.72rem;">Price source: {price_source}</div>
                    {stale_badge}
                </div>
            </div>
            """
        )

    grid_html = (
        f'<div style="display:grid;'
        f"grid-template-columns:repeat(auto-fill,minmax({CARD_MIN_WIDTH}px,1fr));"
        f'gap:12px;margin-top:8px;">'
        + "".join(card_items_html)
        + "</div>"
    )
    st.html(grid_html)
