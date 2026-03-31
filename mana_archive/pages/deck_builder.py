"""Deck Builder page – pull cards from drawers, manage virtual decks."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import func
from sqlmodel import Session, select

from mana_archive.database import get_engine, get_session
from mana_archive.inventory_service import pull_card_to_deck, return_card_from_deck
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


def _list_decks() -> list[str]:
    """Return distinct deck names currently in the inventory."""
    with Session(get_engine()) as session:
        stmt = (
            select(Inventory.location_tag)
            .where(Inventory.location_tag.is_not(None))
            .where(Inventory.drawer == 0)
            .distinct()
        )
        tags = session.exec(stmt).all()
        return [t.removeprefix("DECK:") for t in tags if t]


def _deck_contents(deck_name: str) -> list[dict]:
    """Return all inventory entries for the given deck name."""
    with Session(get_engine()) as session:
        tag = f"DECK:{deck_name}"
        stmt = (
            select(Inventory, Card)
            .join(Card, Inventory.card_id == Card.id)
            .where(Inventory.location_tag == tag)
            .order_by(Card.name)
        )
        rows = session.exec(stmt).all()
        return [
            {
                "inv_id": inv.id,
                "name": card.name,
                "set_name": card.set_name,
                "set_code": card.set_code,
                "finish": inv.finish.value,
                "quantity": inv.quantity,
                "price_usd": card.price_usd,
                "image_uri": card.image_uri,
                "type_line": card.type_line,
            }
            for inv, card in rows
        ]


def _search_collection(query: str) -> list[dict]:
    """Search placed collection cards by name fragment."""
    with Session(get_engine()) as session:
        stmt = (
            select(Inventory, Card)
            .join(Card, Inventory.card_id == Card.id)
            .where(Inventory.drawer != 0)
            .where(Inventory.is_placed == True)  # noqa: E712
            .where(func.lower(Card.name).contains(query.lower()))
            .order_by(Card.name)
            .limit(30)
        )
        rows = session.exec(stmt).all()
        return [
            {
                "inv_id": inv.id,
                "name": card.name,
                "finish": inv.finish.value,
                "drawer": inv.drawer,
                "position": inv.position,
                "quantity": inv.quantity,
                "price_usd": card.price_usd,
                "image_uri": card.image_uri,
            }
            for inv, card in rows
        ]


def render() -> None:
    st.header("Deck Builder")

    tab_build, tab_view = st.tabs(["Build / Pull Cards", "View Decks"])

    # ------------------------------------------------------------------
    # Build / Pull Cards
    # ------------------------------------------------------------------
    with tab_build:
        st.markdown("Search your collection and pull cards into a named deck.")

        deck_name_input = st.text_input(
            "Deck Name",
            placeholder="My Commander Deck",
            key="deck_name_pull",
        )

        search_query = st.text_input(
            "Search Collection",
            placeholder="Counterspell",
            key="pull_search",
        )

        if search_query:
            results = _search_collection(search_query)
            if not results:
                st.info("No placed cards found matching that name.")
            else:
                for row in results:
                    col_img, col_info, col_action = st.columns([1, 5, 2])

                    with col_img:
                        if row["image_uri"]:
                            st.image(row["image_uri"], width=65)

                    with col_info:
                        drawer_label = DRAWER_LABELS.get(row["drawer"], f"Drawer {row['drawer']}")
                        price_str = f"${row['price_usd']:.2f}" if row["price_usd"] else "—"
                        st.markdown(
                            f"**{row['name']}** ({row['finish'].capitalize()})  \n"
                            f"{drawer_label}  ·  Position {row['position']}  ·  "
                            f"Qty Available: **{row['quantity']}**  ·  {price_str}"
                        )

                    with col_action:
                        qty_key = f"pull_qty_{row['inv_id']}"
                        pull_qty = st.number_input(
                            "Qty",
                            min_value=1,
                            max_value=row["quantity"],
                            value=1,
                            key=qty_key,
                        )
                        if st.button("Pull", key=f"pull_{row['inv_id']}", type="primary"):
                            if not deck_name_input.strip():
                                st.warning("Enter a deck name first.")
                            else:
                                with get_session() as session:
                                    pull_card_to_deck(
                                        session,
                                        row["inv_id"],
                                        deck_name_input.strip(),
                                        pull_qty,
                                    )
                                st.success(
                                    f"Pulled {pull_qty}x **{row['name']}** to **{deck_name_input}**."
                                )
                                st.rerun()

                    st.divider()

    # ------------------------------------------------------------------
    # View Decks
    # ------------------------------------------------------------------
    with tab_view:
        decks = _list_decks()

        if not decks:
            st.info("No decks yet. Pull cards from your collection to create one.")
            return

        selected_deck = st.selectbox("Select Deck", decks, key="view_deck_select")

        if not selected_deck:
            return

        contents = _deck_contents(selected_deck)
        total_cards = sum(r["quantity"] for r in contents)
        total_value = sum(
            (r["price_usd"] or 0) * r["quantity"] for r in contents
        )

        col1, col2, col3 = st.columns(3)
        col1.metric("Deck", selected_deck)
        col2.metric("Total Cards", total_cards)
        col3.metric("Estimated Value", f"${total_value:.2f}")

        st.divider()

        for row in contents:
            col_img, col_info, col_action = st.columns([1, 5, 2])

            with col_img:
                if row["image_uri"]:
                    st.image(row["image_uri"], width=65)

            with col_info:
                price_str = f"${row['price_usd']:.2f}" if row["price_usd"] else "—"
                st.markdown(
                    f"**{row['name']}** ({row['finish'].capitalize()})  \n"
                    f"*{row['type_line']}*  ·  "
                    f"{row['set_name']} ({row['set_code'].upper()})  ·  "
                    f"Qty: **{row['quantity']}**  ·  {price_str}"
                )

            with col_action:
                ret_key = f"ret_qty_{row['inv_id']}"
                ret_qty = st.number_input(
                    "Qty",
                    min_value=1,
                    max_value=row["quantity"],
                    value=1,
                    key=ret_key,
                )
                if st.button("Return", key=f"return_{row['inv_id']}"):
                    with get_session() as session:
                        return_card_from_deck(session, row["inv_id"], ret_qty)
                    st.success(f"Returned {ret_qty}x **{row['name']}** to collection.")
                    st.rerun()

            st.divider()
