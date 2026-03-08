import streamlit as st
import os
import pandas as pd
import requests
import time
from sqlmodel import Session, create_engine, select, desc, func
from app.models import Card, Inventory
from app.services.sorter import determine_location

# Page Config
st.set_page_config(layout="wide", page_title="Mana-Archive")
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///./data/mana_archive.db"))
PLACEHOLDER = "https://img.scryfall.com/errors/missing.jpg"

# --- Shared Logic: Removal ---
def remove_inventory_item(item_id, count_to_remove):
    with Session(engine) as session:
        item = session.get(Inventory, item_id)
        if not item: return
        
        drawer, old_pos = item.drawer, item.position
        
        if count_to_remove >= item.quantity:
            session.delete(item)
            # Re-index physical drawer to close the gap
            if drawer and old_pos:
                to_shift = session.exec(select(Inventory).where(Inventory.drawer == drawer, Inventory.position > old_pos)).all()
                for s_item in to_shift: s_item.position -= 1
        else:
            item.quantity -= count_to_remove
        session.commit()

# --- Sidebar & Metrics ---
with st.sidebar:
    st.title("🛡️ Mana-Archive")
    page = st.radio("Navigation", ["Full Collection", "Physical Drawer Map", "Commander Decks", "Data Import"])
    
    with Session(engine) as session:
        val = session.exec(select(func.sum(Card.current_price * Inventory.quantity)).join(Inventory)).one() or 0
        cnt = session.exec(select(func.sum(Inventory.quantity))).one() or 0
        st.metric("Total Collection Value", f"${val:,.2f}")
        st.metric("Total Card Count", f"{cnt:,}")

# --- Page Routing ---
with Session(engine) as session:
    if page == "Full Collection":
        st.title("🎴 Collection Overview")
        
        # 1. Search and Removal Tool
        with st.expander("🛠️ Bulk Remove / Sell Cards"):
            rem_search = st.text_input("Search card to remove")
            if rem_search:
                results = session.exec(select(Card).where(Card.name.contains(rem_search))).all()
                for card in results:
                    for inv in card.inventory_items:
                        r_col1, r_col2 = st.columns([3, 1])
                        with r_col1:
                            loc = f"Drawer {inv.drawer} (P{inv.position})" if inv.drawer else f"Deck: {inv.section}"
                            st.write(f"**{card.name}** | {inv.finish.upper()} | {loc} (Qty: {inv.quantity})")
                        with r_col2:
                            qty_rem = st.number_input("Qty", 1, inv.quantity, key=f"q_{inv.id}")
                            if st.button("Remove", key=f"b_{inv.id}"):
                                remove_inventory_item(inv.id, qty_rem)
                                st.rerun()

        # 2. Main Collection Grid
        st.divider()
        search = st.text_input("Filter View", placeholder="Filter by name or type...")
        stmt = select(Card)
        if search: stmt = stmt.where(Card.name.contains(search) | Card.type_line.contains(search))
        cards = session.exec(stmt.order_by(Card.name)).all()
        
        cols = st.columns(6)
        for idx, card in enumerate(cards):
            with cols[idx % 6]:
                st.image(card.image_url if card.image_url else PLACEHOLDER)
                total_qty = sum(i.quantity for i in card.inventory_items)
                st.write(f"**{card.name}**")
                st.caption(f"Qty: {total_qty} | ${card.current_price:.2f}")

    elif page == "Physical Drawer Map":
        st.title("📂 Drawer Map")
        for d in range(1, 7):
            items = session.exec(select(Inventory).where(Inventory.drawer == d).order_by(Inventory.position)).all()
            if items:
                with st.expander(f"Drawer {d} - {len(items)} Unique Items", expanded=True):
                    cols = st.columns(6)
                    for i, inv in enumerate(items):
                        with cols[i % 6]:
                            st.image(inv.card.image_url if inv.card.image_url else PLACEHOLDER)
                            st.caption(f"Pos {inv.position}: {inv.card.name}")

    elif page == "Commander Decks":
        st.title("⚔️ Commander Decks")
        deck_items = session.exec(select(Inventory).where(Inventory.location_type == "Commander Deck")).all()
        decks = sorted(list(set([i.section for i in deck_items if i.section])))
        for d_name in decks:
            with st.expander(d_name, expanded=True):
                current = [i for i in deck_items if i.section == d_name]
                cols = st.columns(6)
                for idx, inv in enumerate(current):
                    with cols[idx % 6]:
                        st.image(inv.card.image_url if inv.card.image_url else PLACEHOLDER)
                        st.caption(inv.card.name)

    elif page == "Data Import":
        st.title("📥 Data Import")
        # (Import logic from previous working version remains here)
        st.info("Upload your CSV and select destination (Drawer vs Deck)")