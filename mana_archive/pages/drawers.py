"""Drawers page – physical drawer view with cards in position order."""
from __future__ import annotations

from html import escape
from textwrap import dedent

import streamlit as st
from sqlmodel import Session, select

from mana_archive.database import get_engine, get_session
from mana_archive.inventory_service import remove_inventory_entry
from mana_archive.logging_config import get_logger
from mana_archive.models import Card, Inventory
from mana_archive.pricing import get_price_for_finish

log = get_logger(__name__)

DRAWER_LABELS = {
    1: "Drawer 1 – Value ($5+)",
    2: "Drawer 2 – Sets A–D",
    3: "Drawer 3 – Sets E–L",
    4: "Drawer 4 – Sets M–R",
    5: "Drawer 5 – Sets S–Z",
    6: "Drawer 6 – Non-alpha sets (2x2, etc.)",
}

CARD_MIN_WIDTH = 180  # slightly tighter than Browse so more fit per drawer row


def _effective_price(card: dict) -> float | None:
    """Return the finish-aware effective price for an inventory row."""
    return get_price_for_finish(card, card.get("finish"))


def _load_drawer(drawer_num: int) -> list[dict]:
    """Return all inventory entries for a drawer, ordered by position."""
    with Session(get_engine()) as session:
        stmt = (
            select(Inventory, Card)
            .join(Card, Inventory.card_id == Card.id)
            .where(Inventory.drawer == drawer_num)
            .order_by(Inventory.position)
        )
        rows = session.exec(stmt).all()
        return [
            {
                "inv_id": inv.id,
                "position": inv.position,
                "name": card.name,
                "set_code": card.set_code,
                "set_name": card.set_name,
                "collector_number": card.collector_number,
                "type_line": card.type_line,
                "finish": inv.finish.value,
                "quantity": inv.quantity,
                "is_placed": inv.is_placed,
                "price_usd": card.price_usd,
                "price_usd_foil": card.price_usd_foil,
                "price_usd_etched": getattr(card, "price_usd_etched", None),
                "image_uri": card.image_uri,
                "scryfall_url": f"https://scryfall.com/card/{card.set_code.lower()}/{card.collector_number}",
            }
            for inv, card in rows
        ]


def _drawer_stats() -> dict[int, dict]:
    """Return card count, total copies, finish-aware total value, and unplaced count per drawer."""
    with Session(get_engine()) as session:
        stmt = (
            select(Inventory, Card)
            .join(Card, Inventory.card_id == Card.id)
            .where(Inventory.drawer != 0)
        )
        rows = session.exec(stmt).all()

    summary: dict[int, dict] = {}
    for inv, card in rows:
        drawer = inv.drawer
        if drawer not in summary:
            summary[drawer] = {
                "entries": 0,
                "copies": 0,
                "value": 0.0,
                "unplaced": 0,
            }

        row_data = {
            "finish": inv.finish.value if inv.finish else "",
            "price_usd": card.price_usd,
            "price_usd_foil": card.price_usd_foil,
                "price_usd_etched": getattr(card, "price_usd_etched", None),
        }
        effective_price = _effective_price(row_data) or 0.0

        summary[drawer]["entries"] += 1
        summary[drawer]["copies"] += inv.quantity or 0
        summary[drawer]["value"] += effective_price * (inv.quantity or 0)
        if not inv.is_placed:
            summary[drawer]["unplaced"] += 1

    return summary


def _card_grid_html(cards: list[dict], min_width: int) -> str:
    """Render an ordered card grid as a single HTML block."""
    total = len(cards)
    items = []

    for card in cards:
        effective_price = _effective_price(card)
        price_str = f"${effective_price:.2f}" if effective_price is not None else "—"
        placed_color = "#4caf50" if card["is_placed"] else "#ff9800"
        placed_label = "✓ Placed" if card["is_placed"] else "⏳ Pending"

        name_html = escape(card["name"])
        set_name_html = escape(card["set_name"])
        collector_number_html = escape(str(card["collector_number"]))
        scryfall_url = escape(card["scryfall_url"])
        finish_label = escape(card["finish"].capitalize())

        if card["image_uri"]:
            image_uri = escape(card["image_uri"])
            img_html = (
                f'<img src="{image_uri}" '
                f'alt="{name_html}" '
                f'style="width:100%;border-radius:6px 6px 0 0;display:block;">'
            )
        else:
            img_html = (
                '<div style="width:100%;aspect-ratio:5/7;background:#2a2a2a;'
                'display:flex;align-items:center;justify-content:center;'
                'border-radius:6px 6px 0 0;color:#666;font-size:0.75rem">'
                "No image</div>"
            )

        items.append(dedent(f"""
            <div style="background:#1e1e1e;border:1px solid #333;border-radius:8px;
                        overflow:hidden;display:flex;flex-direction:column;">
                {img_html}
                <div style="padding:7px 9px;font-size:0.75rem;line-height:1.5;color:#ddd;">
                    <div style="font-weight:600;font-size:0.82rem;color:#fff;
                                margin-bottom:3px;white-space:nowrap;overflow:hidden;
                                text-overflow:ellipsis;" title="{name_html}">
                        <a href="{scryfall_url}" target="_blank" rel="noopener noreferrer"
                           style="color:#8ec5ff;text-decoration:none;">
                            {name_html}
                        </a>
                    </div>
                    <div style="color:#aaa;margin-bottom:3px;">
                        {set_name_html}&nbsp;·&nbsp;#{collector_number_html}
                    </div>
                    <div style="margin-bottom:3px;">
                        {finish_label}&nbsp;·&nbsp;Qty&nbsp;{card["quantity"]}&nbsp;·&nbsp;
                        <strong style="color:#e8c96a;">{price_str}</strong>
                    </div>
                    <div style="display:flex;justify-content:space-between;
                                align-items:center;margin-top:4px;gap:4px;">
                        <span style="background:#2d2d2d;color:#ccc;
                                     font-size:0.7rem;font-weight:700;
                                     padding:2px 7px;border-radius:4px;
                                     border:1px solid #444;white-space:nowrap;">
                            Position {card["position"]} of {total}
                        </span>
                        <span style="background:{placed_color};color:#000;
                                     font-size:0.68rem;font-weight:700;
                                     padding:2px 6px;border-radius:4px;
                                     white-space:nowrap;">
                            {placed_label}
                        </span>
                    </div>
                </div>
            </div>
            """).strip())

    return (
        f'<div style="display:grid;'
        f"grid-template-columns:repeat(auto-fill,minmax({min_width}px,1fr));"
        f'gap:10px;margin:6px 0 16px 0;">'
        + "".join(items)
        + "</div>"
    )


def render() -> None:
    st.header("Drawers")
    st.caption(
        "Each section shows one physical drawer's contents in their exact "
        "stored order. Position numbers are shown on each card."
    )

    stats = _drawer_stats()

    total_value = sum(s["value"] for s in stats.values())
    total_copies = sum(s["copies"] for s in stats.values())
    total_unplaced = sum(s["unplaced"] for s in stats.values())

    m1, m2, m3, _spacer = st.columns([2, 2, 2, 6])
    m1.metric("Collection Value", f"${total_value:,.2f}")
    m2.metric("Total Copies", f"{total_copies:,}")
    if total_unplaced:
        m3.metric(
            "Pending Placement",
            total_unplaced,
            delta=f"-{total_unplaced} unplaced",
            delta_color="inverse",
        )
    else:
        m3.metric("Pending Placement", "All placed ✅")

    st.divider()

    for drawer_num in range(1, 7):
        s = stats.get(drawer_num, {"entries": 0, "copies": 0, "value": 0.0, "unplaced": 0})
        label = DRAWER_LABELS[drawer_num]
        copies_str = f"{s['copies']:,} cop{'y' if s['copies'] == 1 else 'ies'}"
        value_str = f"${s['value']:,.2f}"
        unplaced_str = f"  ·  ⚠ {s['unplaced']} unplaced" if s["unplaced"] else ""
        header = f"{label}  ·  {copies_str}  ·  {value_str}{unplaced_str}"

        with st.expander(header, expanded=s["entries"] > 0):
            if s["entries"] == 0:
                st.caption("This drawer is empty.")
                continue

            cards = _load_drawer(drawer_num)
            st.markdown(_card_grid_html(cards, CARD_MIN_WIDTH), unsafe_allow_html=True)

            st.markdown("##### Remove card from this drawer")
            options = {card["inv_id"]: card for card in cards}
            selected_inv_id = st.selectbox(
                "Select card to remove",
                options=list(options.keys()),
                format_func=lambda inv_id: (
                    f"Pos {options[inv_id]['position']} · {options[inv_id]['name']} · "
                    f"{options[inv_id]['finish'].capitalize()} · Qty {options[inv_id]['quantity']}"
                ),
                key=f"remove_select_{drawer_num}",
            )
            selected_card = options[selected_inv_id]
            remove_all = st.checkbox(
                "Remove all copies",
                value=True,
                key=f"remove_all_{drawer_num}",
            )
            qty_to_remove = selected_card["quantity"]
            if not remove_all:
                qty_to_remove = st.number_input(
                    "Quantity to remove",
                    min_value=1,
                    max_value=selected_card["quantity"],
                    value=1,
                    step=1,
                    key=f"remove_qty_{drawer_num}",
                )
            reason = st.selectbox(
                "Reason",
                ["Sold", "Traded", "Removed"],
                key=f"remove_reason_{drawer_num}",
            )
            confirm = st.checkbox(
                "I understand this will remove the selected card from inventory",
                key=f"remove_confirm_{drawer_num}",
            )
            if st.button(
                "Remove selected card",
                key=f"remove_btn_{drawer_num}",
                disabled=not confirm,
            ):
                with get_session() as session:
                    result = remove_inventory_entry(
                        session,
                        selected_inv_id,
                        quantity=None if remove_all else int(qty_to_remove),
                        reason=f"{reason}",
                    )
                st.success(
                    f"{reason}: removed {result['removed']}x {result['name']} from drawer {result['drawer']}."
                )
                st.rerun()