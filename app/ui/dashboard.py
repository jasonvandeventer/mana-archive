import streamlit as st
import os
import pandas as pd
import requests
import time
import re
from datetime import datetime
from sqlmodel import Session, create_engine, select, desc, func, col, update
from sqlalchemy import or_
from app.models import Card, Inventory, TransactionLog
from app.services.sorter import determine_location

# --- Configuration & DB Setup ---
st.set_page_config(layout="wide", page_title="Mana-Archive Dashboard")
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/mana_archive.db")
engine = create_engine(DB_URL)
PLACEHOLDER_IMG = "https://img.scryfall.com/errors/missing.jpg"

def natural_key(string_):
    """Natural sort helper: ensures '25' comes before '106'."""
    if not string_: return (0,)
    return tuple(int(s) if s.isdigit() else s.lower() for s in re.split(r'(\d+)', str(string_)))

# --- Shared Logic Functions ---
def remove_inventory_item(item_id, count_to_remove, action_type="REMOVE"):
    """Deletes/reduces inventory and re-indexes physical positions to close gaps."""
    with Session(engine) as session:
        item = session.get(Inventory, item_id)
        if not item: return
        card_name, price, drawer, old_pos = item.card.name, item.card.current_price, item.drawer, item.position
        session.add(TransactionLog(action=action_type, card_name=card_name, quantity=count_to_remove, price_at_time=price, details=f"From {item.location_type} (D:{drawer} P:{old_pos})"))
        if count_to_remove >= item.quantity:
            session.delete(item)
            if drawer and old_pos:
                to_shift = session.exec(select(Inventory).where(Inventory.drawer == drawer, Inventory.position > old_pos)).all()
                for s_item in to_shift: s_item.position -= 1
        else:
            item.quantity -= count_to_remove
        session.commit()

def run_import(uploaded_file, location_type, deck_name=None):
    """Processes CSV import with Scryfall metadata hydration and position calculation."""
    df = pd.read_csv(uploaded_file)
    df.columns = df.columns.str.strip().str.lower()
    df['n_key'] = df['collector number'].apply(natural_key)
    df = df.sort_values(by=['set code', 'n_key']).drop(columns=['n_key'])
    with Session(engine) as session:
        progress_bar = st.progress(0)
        for index, row in df.iterrows():
            sid = str(row['scryfall id'])
            finish = str(row.get('finish', 'nonfoil')).lower()
            qty = int(row.get('quantity', 1))
            time.sleep(0.05) 
            try:
                response = requests.get(f"https://api.scryfall.com/cards/{sid}")
                raw_data = response.json()
                price = float(raw_data.get('prices', {}).get('usd_foil' if 'foil' in finish else 'usd') or 0)
                card_metadata = {
                    "name": raw_data.get('name'),
                    "set_code": raw_data.get('set').lower(),
                    "coll_num": str(raw_data.get('collector_number')),
                    "colors": ",".join(raw_data.get('colors', [])),
                    "cmc": float(raw_data.get('cmc', 0.0)),
                    "type_line": raw_data.get('type_line', ""),
                    "img": (raw_data.get('image_uris', {}).get('normal') or 
                            raw_data.get('card_faces', [{}])[0].get('image_uris', {}).get('normal'))
                }
            except: continue

            card = session.exec(select(Card).where(Card.scryfall_id == sid)).first()
            if not card:
                card = Card(name=card_metadata['name'], set_code=card_metadata['set_code'], 
                            scryfall_id=sid, current_price=price, image_url=card_metadata['img'], 
                            collector_number=card_metadata['coll_num'], colors=card_metadata['colors'],
                            cmc=card_metadata['cmc'], type_line=card_metadata['type_line'])
                session.add(card); session.flush()

            drawer, section = None, deck_name
            if location_type == "Drawer": drawer, section = determine_location(price, card_metadata['set_code'])
            
            existing = session.exec(select(Inventory).where(Inventory.card_id == card.id, Inventory.drawer == drawer, Inventory.finish == finish)).first()
            if existing:
                existing.quantity += qty
                if location_type == "Drawer": existing.is_placed = False 
            else:
                pos = 1
                if location_type == "Drawer":
                    existing_inv = session.exec(select(Inventory).join(Card).where(Inventory.drawer == drawer)).all()
                    existing_inv.sort(key=lambda x: (x.card.set_code, natural_key(x.card.collector_number)))
                    new_key = natural_key(card_metadata['coll_num'])
                    for item in existing_inv:
                        if (item.card.set_code > card_metadata['set_code']) or (item.card.set_code == card_metadata['set_code'] and natural_key(item.card.collector_number) > new_key):
                            pos = item.position; break
                        pos = item.position + 1
                    to_shift = session.exec(select(Inventory).where(Inventory.drawer == drawer, Inventory.position >= pos)).all()
                    for s in to_shift: s.position += 1
                session.add(Inventory(card_id=card.id, drawer=drawer, section=section, quantity=qty, position=pos, location_type=location_type, finish=finish, is_placed=(location_type != "Drawer")))
            session.add(TransactionLog(action="IMPORT", card_name=card_metadata['name'], quantity=qty, price_at_time=price, details=f"Target: {location_type}"))
            session.commit()
            progress_bar.progress((index + 1) / len(df))
        st.success("Import Complete!")

# --- Sidebar ---
with st.sidebar:
    st.title("🛡️ Mana-Archive")
    page = st.radio("Navigation", ["Full Collection", "Pending Placement", "Physical Drawer Map", "Commander Decks", "Deck Builder", "Data Import", "Transaction History", "Physical Audit", "Fuzzy Lookup"])
    st.divider()
    sort_pref = st.selectbox("Global Sort Preference", [
        "Numerical (Set/Collector #)", 
        "Alphabetical (Name)", 
        "Price (Highest First)",
        "Price (Lowest First)",
        "Mana Value (Highest First)", 
        "Mana Value (Lowest First)", 
        "Color Identity", 
        "Card Type"
    ])
    with Session(engine) as session:
        val = session.exec(select(func.sum(Card.current_price * Inventory.quantity)).join(Inventory)).one() or 0
        qty = session.exec(select(func.sum(Inventory.quantity))).one() or 0
        st.metric("Total Value", f"${val:,.2f}")
        st.metric("Total Count", f"{qty:,}")

# --- Page Routing ---
with Session(engine) as session:
    if page == "Full Collection":
        st.title("🎴 Collection Overview")
        with st.expander("🛠️ Bulk Remove / Sell Cards"):
            rem_q = st.text_input("Search card to remove")
            if rem_q:
                res = session.exec(select(Card).where(col(Card.name).ilike(f"%{rem_q}%"))).all()
                for c in res:
                    for inv in c.inventory_items:
                        r1, r2 = st.columns([3, 1])
                        with r1: st.write(f"**{c.name}** | {inv.finish.upper()} | D:{inv.drawer} P:{inv.position}")
                        with r2: 
                            if st.button("Remove 1", key=f"rem_{inv.id}"): remove_inventory_item(inv.id, 1); st.rerun()
        st.divider()
        c1, c2 = st.columns([3, 1])
        with c1: search = st.text_input("Global Search", placeholder="Name, type, set, or colors...")
        with c2: color_filter = st.multiselect("Color Filter", ["W", "U", "B", "R", "G", "C"])
        
        stmt = select(Card)
        if search:
            s = f"%{search}%"
            stmt = stmt.where(or_(col(Card.name).ilike(s), col(Card.type_line).ilike(s), col(Card.set_code).ilike(s), col(Card.colors).ilike(s)))
        if color_filter:
            if "C" in color_filter: stmt = stmt.where((Card.colors == "") | (Card.colors == None))
            else:
                conds = [col(Card.colors).contains(c) for c in color_filter if c != "C"]
                stmt = stmt.where(or_(*conds))
        
        cards = session.exec(stmt).all()
        color_order = {"W": 1, "U": 2, "B": 3, "R": 4, "G": 5, "": 6}
        
        if sort_pref == "Alphabetical (Name)": 
            cards.sort(key=lambda x: x.name)
        elif "Price" in sort_pref:
            cards.sort(key=lambda x: x.current_price or 0, reverse=("Highest" in sort_pref))
        elif "Mana Value" in sort_pref: 
            cards.sort(key=lambda x: x.cmc or 0, reverse=("Highest" in sort_pref))
        elif sort_pref == "Card Type": 
            cards.sort(key=lambda x: (x.type_line or "", x.name))
        elif sort_pref == "Color Identity": 
            cards.sort(key=lambda x: (len(x.colors or ""), color_order.get(x.colors[0] if x.colors else "", 7), x.name))
        else: 
            cards.sort(key=lambda x: (x.set_code, natural_key(x.collector_number)))
        
        cols = st.columns(6)
        for idx, card in enumerate(cards):
            with cols[idx % 6]:
                st.image(card.image_url if card.image_url else PLACEHOLDER_IMG)
                st.write(f"**{card.name}**")
                price_disp = f"${card.current_price:,.2f}" if card.current_price > 0 else "N/A"
                st.caption(f"#{card.collector_number} ({card.set_code.upper()}) | {price_disp}")

    elif page == "Deck Builder":
        st.title("⚒️ Deck Builder")
        if 'deck_draft' not in st.session_state: st.session_state.deck_draft = []
        name = st.text_input("Deck Name")
        c1, c2 = st.columns([2, 1])
        with c1:
            find = st.text_input("Add Card")
            if find:
                res = session.exec(select(Card).where(col(Card.name).ilike(f"%{find}%"))).all()
                for c in res:
                    d_qty = sum(i.quantity for i in c.inventory_items if i.location_type == "Drawer")
                    if st.button(f"Add {c.name} ({d_qty})", key=f"ad_{c.id}"):
                        inv = session.exec(select(Inventory).where(Inventory.card_id == c.id, Inventory.location_type == "Drawer")).first()
                        if inv: 
                            st.session_state.deck_draft.append({"id": c.id, "name": c.name, "drawer": inv.drawer, "pos": inv.position})
                            st.rerun()
        with c2:
            st.subheader("Pull List")
            st.session_state.deck_draft.sort(key=lambda x: (x['drawer'], x['pos']))
            for e in st.session_state.deck_draft: st.write(f"D{e['drawer']} P{e['pos']} | {e['name']}")
            if st.button("Commit Pull") and name:
                for e in st.session_state.deck_draft:
                    inv = session.exec(select(Inventory).where(Inventory.card_id == e['id'], Inventory.location_type == "Drawer")).first()
                    if inv:
                        remove_inventory_item(inv.id, 1, "DECK_PULL")
                        session.add(Inventory(card_id=e['id'], location_type="Commander Deck", section=name, quantity=1, is_placed=True))
                session.commit(); st.session_state.deck_draft = []; st.success("Deck Assembled!"); st.rerun()

    elif page == "Pending Placement":
        st.title("📥 Pending")
        pending = session.exec(select(Inventory).where(Inventory.is_placed == False).order_by(Inventory.drawer, Inventory.position)).all()
        if st.button("Clear All"):
            for inv in pending: session.delete(inv)
            session.commit(); st.rerun()
        for inv in pending:
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 3, 2])
                with c1: st.image(inv.card.image_url, width=100)
                with c2: st.subheader(inv.card.name); st.write(f"D{inv.drawer} P{inv.position}")
                with c3:
                    if st.button("Placed", key=f"pl_{inv.id}"): inv.is_placed = True; session.commit(); st.rerun()
                    if st.button("Err", key=f"er_{inv.id}"): remove_inventory_item(inv.id, inv.quantity); st.rerun()

    elif page == "Physical Drawer Map":
        st.title("📂 Map")
        for d in range(1, 7):
            items = session.exec(select(Inventory).where(Inventory.drawer == d).order_by(Inventory.position)).all()
            with st.expander(f"Drawer {d}"):
                cols = st.columns(6)
                for i, inv in enumerate(items):
                    with cols[i % 6]:
                        if not inv.is_placed: st.warning("PENDING")
                        st.image(inv.card.image_url); st.caption(f"P{inv.position}: #{inv.card.collector_number}")

    elif page == "Physical Audit":
        st.title("🔍 Audit")
        d_audit = st.selectbox("Select Drawer", range(1, 7))
        items = session.exec(select(Inventory).where(Inventory.drawer == d_audit).order_by(Inventory.position)).all()
        if items:
            if 'audit_idx' not in st.session_state or st.session_state.get('curr_d') != d_audit:
                st.session_state.audit_idx = 0; st.session_state.curr_d = d_audit
            idx = st.session_state.audit_idx
            if idx < len(items):
                item = items[idx]
                st.progress(idx / len(items))
                col1, col2 = st.columns([1, 2])
                with col1: st.image(item.card.image_url)
                with col2:
                    st.write(f"### {item.card.name}"); st.write(f"Pos {item.position} | #{item.card.collector_number}")
                    if st.button("✅ Next"): st.session_state.audit_idx += 1; st.rerun()
                    if st.button("❌ Error"): item.is_placed = False; session.commit(); st.session_state.audit_idx += 1; st.rerun()
            else:
                st.success("Complete!"); 
                if st.button("Restart"): st.session_state.audit_idx = 0; st.rerun()

    elif page == "Transaction History":
        st.title("📜 Logs")
        logs = session.exec(select(TransactionLog).order_by(desc(TransactionLog.timestamp))).all()
        st.dataframe(pd.DataFrame([l.model_dump() for l in logs]), use_container_width=True)

    elif page == "Commander Decks":
        st.title("⚔️ Commander Decks")
        # Query all items currently assigned to a deck
        deck_items = session.exec(select(Inventory).where(Inventory.location_type == "Commander Deck")).all()
        
        # Get unique deck names
        deck_names = sorted(list(set([i.section for i in deck_items if i.section])))
        
        if not deck_names:
            st.info("No decks assembled yet. Use the Deck Builder to pull cards from your drawers.")
        else:
            for deck in deck_names:
                # Filter items for this specific deck
                current_deck_cards = [i for i in deck_items if i.section == deck]
                
                # Logical Aggregation: Calculate total value and card count
                deck_value = sum((i.card.current_price or 0) * i.quantity for i in current_deck_cards)
                deck_count = sum(i.quantity for i in current_deck_cards)
                
                # UI Layout: Use an expander with metrics in the header
                with st.expander(f"{deck}"):
                    m1, m2 = st.columns(2)
                    m1.metric("Estimated Value", f"${deck_value:,.2f}")
                    m2.metric("Card Count", f"{deck_count}/100")
                    
                    st.divider()
                    
                    # Grid display of cards in the deck
                    cols = st.columns(6)
                    for idx, inv in enumerate(current_deck_cards):
                        with cols[idx % 6]:
                            st.image(inv.card.image_url if inv.card.image_url else PLACEHOLDER_IMG)
                            st.write(f"**{inv.card.name}**")
                            st.caption(f"${inv.card.current_price:,.2f}")
    elif page == "Data Import":
        st.title("📥 Import")
        it = st.selectbox("Dest", ["Drawer", "Deck"])
        dn = st.text_input("Deck Name") if it == "Deck" else None
        uf = st.file_uploader("CSV", type=["csv"])
        if uf and st.button("Run"): run_import(uf, "Drawer" if it == "Drawer" else "Commander Deck", dn)

    elif page == "Fuzzy Lookup":
        st.title("🔍 Scryfall")
        q = st.text_input("Card Name")
        if q:
            res = requests.get(f"https://api.scryfall.com/cards/named?fuzzy={q}")
            if res.status_code == 200:
                data = res.json(); c1, c2 = st.columns([1, 2])
                with c1: st.image(data.get('image_uris', {}).get('normal', PLACEHOLDER_IMG))
                with c2: st.write(f"## {data['name']}"); st.write(f"**Set:** {data['set'].upper()} | **Price:** ${data.get('prices', {}).get('usd', 'N/A')}")