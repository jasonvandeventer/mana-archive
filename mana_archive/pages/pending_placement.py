"""Pending Placement page – confirm cards have been physically filed."""
from __future__ import annotations

import streamlit as st
from sqlmodel import Session, select

from mana_archive.database import get_engine, get_session
from mana_archive.inventory_service import (
    confirm_all_pending,
    confirm_placement,
    undo_last_batch,
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


def _load_pending() -> list[tuple[Inventory, Card]]:
    """Return all unplaced inventory entries joined with their card."""
    with Session(get_engine()) as session:
        stmt = (
            select(Inventory, Card)
            .join(Card, Inventory.card_id == Card.id)
            .where(Inventory.is_placed == False)  # noqa: E712
            .order_by(Inventory.drawer, Inventory.position)
        )
        rows = session.exec(stmt).all()
        result = []
        for inv, card in rows:
            # Detach from session by creating plain dicts
            result.append(
                {
                    "inv_id": inv.id,
                    "card_id": card.id,
                    "name": card.name,
                    "set_name": card.set_name,
                    "set_code": card.set_code,
                    "finish": inv.finish.value,
                    "drawer": inv.drawer,
                    "position": inv.position,
                    "quantity": inv.quantity,
                    "price_usd": card.price_usd,
                    "image_uri": card.image_uri,
                }
            )
        return result


def render() -> None:
    st.header("Pending Placement")
    st.caption(
        "Cards listed here have been imported into the database but not yet physically "
        "filed in their drawer. Confirm each card once it has been placed."
    )

    pending = _load_pending()

    if not pending:
        st.success("All cards have been physically placed. Nothing pending!")
        return

    # Summary metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Pending Cards", len(pending))
    drawers_affected = len({r["drawer"] for r in pending})
    col2.metric("Drawers Affected", drawers_affected)
    col3.metric(
        "Total Copies",
        sum(r["quantity"] for r in pending),
    )

    st.divider()

    action_col, undo_col = st.columns([3, 2])

    with action_col:
        if st.button("Confirm ALL as Placed", type="primary", key="btn_confirm_all"):
            with get_session() as session:
                count = confirm_all_pending(session)
            st.success(f"Confirmed {count} entries as placed.")
            st.rerun()

    with undo_col:
        if st.button("↩ Undo Last Batch Import", key="btn_undo_batch"):
            st.session_state["undo_batch_confirm"] = True

    if st.session_state.get("undo_batch_confirm"):
        st.warning(
            "This will reverse the most recent CSV batch import — removing every "
            "card that was part of that import. Proceed?"
        )
        yes_col, no_col = st.columns(2)
        if yes_col.button("Yes, undo batch", key="btn_undo_batch_yes", type="primary"):
            try:
                with get_session() as session:
                    result = undo_last_batch(session)
                n = result["removed"] + result["updated"]
                batch_label = result["batch_id"]
                st.success(
                    f"Reversed batch `{batch_label}` — "
                    f"{n} card(s) removed/decremented across "
                    f"{len(result['drawers'])} drawer(s)."
                )
            except ValueError as exc:
                st.error(str(exc))
            st.session_state["undo_batch_confirm"] = False
            st.rerun()
        if no_col.button("Cancel", key="btn_undo_batch_no"):
            st.session_state["undo_batch_confirm"] = False
            st.rerun()

    st.divider()

    # Group by drawer
    by_drawer: dict[int, list[dict]] = {}
    for row in pending:
        by_drawer.setdefault(row["drawer"], []).append(row)

    for drawer_num in sorted(by_drawer.keys()):
        rows = by_drawer[drawer_num]
        label = DRAWER_LABELS.get(drawer_num, f"Drawer {drawer_num}")
        with st.expander(f"{label}  ({len(rows)} pending)", expanded=True):
            for row in rows:
                col_img, col_info, col_action = st.columns([1, 4, 1])

                with col_img:
                    if row["image_uri"]:
                        st.image(row["image_uri"], width=80)
                    else:
                        st.write("—")

                with col_info:
                    price_str = f"${row['price_usd']:.2f}" if row["price_usd"] else "N/A"
                    st.markdown(
                        f"**{row['name']}**  \n"
                        f"{row['set_name']} ({row['set_code'].upper()})  ·  "
                        f"{row['finish'].capitalize()}  ·  "
                        f"Qty: {row['quantity']}  ·  "
                        f"Price: {price_str}  \n"
                        f"Position **{row['position']}** in {label}"
                    )

                with col_action:
                    if st.button(
                        "Confirm",
                        key=f"confirm_{row['inv_id']}",
                        type="primary",
                    ):
                        with get_session() as session:
                            confirm_placement(session, row["inv_id"])
                        st.rerun()
