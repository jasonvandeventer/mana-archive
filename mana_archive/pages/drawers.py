"""Drawers page – physical drawer view with cards in position order."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import func
from sqlmodel import Session, select

from mana_archive.database import get_engine
from mana_archive.logging_config import get_logger
from mana_archive.models import Card, Inventory

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
                "image_uri": card.image_uri,
            }
            for inv, card in rows
        ]


def _drawer_stats() -> dict[int, dict]:
    """Return card count, total copies, total value, and unplaced count per drawer."""
    with Session(get_engine()) as session:
        from sqlalchemy import Integer

        stmt = (
            select(
                Inventory.drawer,
                func.count(Inventory.id).label("entries"),
                func.sum(Inventory.quantity).label("copies"),
                func.sum(Card.price_usd * Inventory.quantity).label("value"),
                func.sum(
                    func.cast(Inventory.is_placed == False, Integer)  # noqa: E712
                ).label("unplaced"),
            )
            .join(Card, Inventory.card_id == Card.id)
            .where(Inventory.drawer != 0)
            .group_by(Inventory.drawer)
        )
        rows = session.exec(stmt).all()
        return {
            row.drawer: {
                "entries": row.entries or 0,
                "copies": row.copies or 0,
                "value": float(row.value or 0),
                "unplaced": row.unplaced or 0,
            }
            for row in rows
        }


def _card_grid_html(cards: list[dict], min_width: int) -> str:
    """Render an ordered card grid as a single HTML block."""
    total = len(cards)
    items = []
    for card in cards:
        price_str = f"${card['price_usd']:.2f}" if card["price_usd"] else "—"
        placed_color = "#4caf50" if card["is_placed"] else "#ff9800"
        placed_label = "✓ Placed" if card["is_placed"] else "⏳ Pending"

        if card["image_uri"]:
            img_html = (
                f'<img src="{card["image_uri"]}" '
                f'alt="{card["name"]}" '
                f'style="width:100%;border-radius:6px 6px 0 0;display:block;">'
            )
        else:
            img_html = (
                '<div style="width:100%;aspect-ratio:5/7;background:#2a2a2a;'
                'display:flex;align-items:center;justify-content:center;'
                'border-radius:6px 6px 0 0;color:#666;font-size:0.75rem">'
                "No image</div>"
            )

        items.append(
            f"""
            <div style="background:#1e1e1e;border:1px solid #333;border-radius:8px;
                        overflow:hidden;display:flex;flex-direction:column;">
                {img_html}
                <div style="padding:7px 9px;font-size:0.75rem;line-height:1.5;color:#ddd;">
                    <div style="font-weight:600;font-size:0.82rem;color:#fff;
                                margin-bottom:3px;white-space:nowrap;overflow:hidden;
                                text-overflow:ellipsis;" title="{card["name"]}">
                        {card["name"]}
                    </div>
                    <div style="color:#aaa;margin-bottom:3px;">
                        {card["set_name"]}&nbsp;·&nbsp;#{card["collector_number"]}
                    </div>
                    <div style="margin-bottom:3px;">
                        {card["finish"].capitalize()}&nbsp;·&nbsp;Qty&nbsp;{card["quantity"]}&nbsp;·&nbsp;<strong style="color:#e8c96a;">{price_str}</strong>
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
            """
        )

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

    # ── Summary bar ───────────────────────────────────────────────────────
    total_value = sum(s["value"] for s in stats.values())
    total_copies = sum(s["copies"] for s in stats.values())
    total_unplaced = sum(s["unplaced"] for s in stats.values())

    m1, m2, m3, _spacer = st.columns([2, 2, 2, 6])
    m1.metric("Collection Value", f"${total_value:,.2f}")
    m2.metric("Total Copies", f"{total_copies:,}")
    if total_unplaced:
        m3.metric("Pending Placement", total_unplaced, delta=f"-{total_unplaced} unplaced",
                  delta_color="inverse")
    else:
        m3.metric("Pending Placement", "All placed ✅")

    st.divider()

    # ── One expander per drawer ───────────────────────────────────────────
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
            st.html(_card_grid_html(cards, CARD_MIN_WIDTH))
