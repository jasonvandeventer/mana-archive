import streamlit as st
import os
from sqlmodel import Session, create_engine, select
from app.models import Card, Inventory

st.set_page_config(layout="wide", page_title="Mana-Archive")
st.title("🎴 Mana-Archive: Visual Catalog")

db_url = os.getenv("DATABASE_URL", "sqlite:///./data/mana_archive.db")
engine = create_engine(db_url)

with st.sidebar:
    st.header("Search Filters")
    name_q = st.text_input("Card Name")
    type_q = st.text_input("Type Line")

with Session(engine) as session:
    stmt = select(Card)
    if name_q: stmt = stmt.where(Card.name.icontains(name_q))
    if type_q: stmt = stmt.where(Card.type_line.icontains(type_q))
    
    cards = session.exec(stmt).all()
    
    if not cards:
        st.warning("No cards found.")
    else:
        # 6-Column Responsive Grid
        cols_per_row = 6
        for i in range(0, len(cards), cols_per_row):
            batch = cards[i:i + cols_per_row]
            cols = st.columns(cols_per_row)
            for j, card in enumerate(batch):
                with cols[j]:
                    st.image(card.image_url, use_container_width=True)
                    st.write(f"**{card.name}**")
                    # Display location details
                    for inv in card.inventory_items:
                        loc_desc = f"Drawer {inv.drawer}" if inv.drawer else "Deck"
                        st.caption(f"📍 {loc_desc} ({inv.section}) x{inv.quantity}")