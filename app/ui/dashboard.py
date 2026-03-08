import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler

import pandas as pd
import requests
import streamlit as st
from sqlalchemy import or_
from sqlmodel import Session, col, create_engine, desc, func, select

from app.models import Card, Inventory, TransactionLog
from app.services.sorter import determine_location

# --- Configuration & DB Setup ---
st.set_page_config(layout="wide", page_title="Mana-Archive Dashboard")
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/mana_archive.db")
engine = create_engine(DB_URL)
PLACEHOLDER_IMG = "https://img.scryfall.com/errors/missing.jpg"

# --- DevOps Logging Configuration ---
os.makedirs("logs", exist_ok=True)
LOG_FILE = "logs/mana_archive.log"
log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

# Rotating handler to prevent disk overflow
my_handler = RotatingFileHandler(
    LOG_FILE, mode="a", maxBytes=5 * 1024 * 1024, backupCount=3, encoding=None, delay=0
)
my_handler.setFormatter(log_formatter)
my_handler.setLevel(logging.INFO)

app_log = logging.getLogger("root")
app_log.setLevel(logging.INFO)
if not app_log.handlers:
    app_log.addHandler(my_handler)


def natural_key(string_):
    """Natural sort helper for alphanumeric strings (e.g., collector numbers)."""
    if not string_:
        return (0,)
    return tuple(
        int(s) if s.isdigit() else s.lower() for s in re.split(r"(\d+)", str(string_))
    )


# --- Shared Logic Functions ---
def remove_inventory_item(item_id, count_to_remove, action_type="REMOVE"):
    """Reduces inventory and re-indexes drawer positions to maintain consistency."""
    with Session(engine) as session:
        item = session.get(Inventory, item_id)
        if not item:
            return
        card_name, price = item.card.name, item.card.current_price
        drawer, old_pos = item.drawer, item.position

        app_log.info(
            f"Action: {action_type} | Card: {card_name} | Qty: {count_to_remove}"
        )

        log_entry = TransactionLog(
            action=action_type,
            card_name=card_name,
            quantity=count_to_remove,
            price_at_time=price,
            details=f"From {item.location_type} (D:{drawer} P:{old_pos})",
        )
        session.add(log_entry)

        if count_to_remove >= item.quantity:
            session.delete(item)
            if drawer and old_pos:
                stmt = select(Inventory).where(
                    Inventory.drawer == drawer, Inventory.position > old_pos
                )
                to_shift = session.exec(stmt).all()
                for s_item in to_shift:
                    s_item.position -= 1
        else:
            item.quantity -= count_to_remove
        session.commit()


def run_import(uploaded_file, location_type, deck_name=None):
    """Processes CSV import with metadata hydration and automated sorting."""
    df = pd.read_csv(uploaded_file)
    df.columns = df.columns.str.strip().str.lower()
    df["n_key"] = df["collector number"].apply(natural_key)
    df = df.sort_values(by=["set code", "n_key"]).drop(columns=["n_key"])

    with Session(engine) as session:
        progress_bar = st.progress(0)
        for index, row in df.iterrows():
            sid = str(row["scryfall id"])
            finish = str(row.get("finish", "nonfoil")).lower()
            qty = int(row.get("quantity", 1))
            time.sleep(0.05)
            try:
                response = requests.get(f"https://api.scryfall.com/cards/{sid}")
                raw_data = response.json()
                price_key = "usd_foil" if "foil" in finish else "usd"
                price = float(raw_data.get("prices", {}).get(price_key) or 0)
                card_meta = {
                    "name": raw_data.get("name"),
                    "set": raw_data.get("set").lower(),
                    "num": str(raw_data.get("collector_number")),
                    "colors": ",".join(raw_data.get("colors", [])),
                    "cmc": float(raw_data.get("cmc", 0.0)),
                    "type": raw_data.get("type_line", ""),
                    "img": (
                        raw_data.get("image_uris", {}).get("normal")
                        or raw_data.get("card_faces", [{}])[0]
                        .get("image_uris", {})
                        .get("normal")
                    ),
                }
            except Exception as e:
                app_log.error(f"Import failed for Scryfall ID {sid}: {e}")
                continue

            card = session.exec(select(Card).where(Card.scryfall_id == sid)).first()
            if not card:
                card = Card(
                    name=card_meta["name"],
                    set_code=card_meta["set"],
                    scryfall_id=sid,
                    current_price=price,
                    image_url=card_meta["img"],
                    collector_number=card_meta["num"],
                    colors=card_meta["colors"],
                    cmc=card_meta["cmc"],
                    type_line=card_meta["type"],
                )
                session.add(card)
                session.flush()

            drawer, section = None, deck_name
            if location_type == "Drawer":
                drawer, section = determine_location(price, card_meta["set"])

            existing = session.exec(
                select(Inventory).where(
                    Inventory.card_id == card.id,
                    Inventory.drawer == drawer,
                    Inventory.finish == finish,
                )
            ).first()

            if existing:
                existing.quantity += qty
                if location_type == "Drawer":
                    existing.is_placed = False
            else:
                pos = 1
                if location_type == "Drawer":
                    inv_stmt = (
                        select(Inventory).join(Card).where(Inventory.drawer == drawer)
                    )
                    e_inv = session.exec(inv_stmt).all()
                    e_inv.sort(
                        key=lambda x: (
                            x.card.set_code,
                            natural_key(x.card.collector_number),
                        )
                    )
                    new_key = natural_key(card_meta["num"])
                    for item in e_inv:
                        if (item.card.set_code > card_meta["set"]) or (
                            item.card.set_code == card_meta["set"]
                            and natural_key(item.card.collector_number) > new_key
                        ):
                            pos = item.position
                            break
                        pos = item.position + 1
                    shift_stmt = select(Inventory).where(
                        Inventory.drawer == drawer, Inventory.position >= pos
                    )
                    for s in session.exec(shift_stmt).all():
                        s.position += 1

                session.add(
                    Inventory(
                        card_id=card.id,
                        drawer=drawer,
                        section=section,
                        quantity=qty,
                        position=pos,
                        location_type=location_type,
                        finish=finish,
                        is_placed=(location_type != "Drawer"),
                    )
                )
            session.commit()
            progress_bar.progress((index + 1) / len(df))
        app_log.info(f"Import successful: {len(df)} records processed.")


# --- Sidebar ---
with st.sidebar:
    st.title("🛡️ Mana-Archive")
    page = st.radio(
        "Navigation",
        [
            "Full Collection",
            "Pending Placement",
            "Physical Drawer Map",
            "Commander Decks",
            "Deck Builder",
            "Data Import",
            "Transaction History",
            "Physical Audit",
            "System Logs",
            "Fuzzy Lookup",
        ],
    )
    st.divider()
    sort_opts = [
        "Numerical (Set/Collector #)",
        "Alphabetical (Name)",
        "Price (Highest First)",
        "Price (Lowest First)",
        "Mana Value (Highest First)",
        "Mana Value (Lowest First)",
        "Color Identity",
        "Card Type",
    ]
    sort_pref = st.selectbox("Global Sort Preference", sort_opts)

    with Session(engine) as session:
        v_stmt = select(func.sum(Card.current_price * Inventory.quantity)).join(
            Inventory
        )
        total_val = session.exec(v_stmt).one() or 0
        total_count = session.exec(select(func.sum(Inventory.quantity))).one() or 0
        st.metric("Total Value", f"${total_val:,.2f}")
        st.metric("Total Count", f"{total_count:,}")

# --- Page Routing ---
with Session(engine) as session:
    if page == "Full Collection":
        st.title("🎴 Collection Overview")
        c1, c2 = st.columns([3, 1])
        with c1:
            search = st.text_input(
                "Global Search", placeholder="Name, type, set, or colors..."
            )
        with c2:
            color_filter = st.multiselect(
                "Color Filter", ["W", "U", "B", "R", "G", "C"]
            )

        stmt = select(Card)
        if search:
            s = f"%{search}%"
            stmt = stmt.where(
                or_(
                    col(Card.name).ilike(s),
                    col(Card.type_line).ilike(s),
                    col(Card.set_code).ilike(s),
                    col(Card.colors).ilike(s),
                )
            )
        if color_filter:
            if "C" in color_filter:
                stmt = stmt.where((Card.colors == "") | (Card.colors.is_(None)))
            else:
                conds = [col(Card.colors).contains(c) for c in color_filter if c != "C"]
                stmt = stmt.where(or_(*conds))

        cards = session.exec(stmt).all()
        c_order = {"W": 1, "U": 2, "B": 3, "R": 4, "G": 5, "": 6}
        if sort_pref == "Alphabetical (Name)":
            cards.sort(key=lambda x: x.name)
        elif "Price" in sort_pref:
            cards.sort(
                key=lambda x: (x.current_price or 0, x.name),
                reverse=("Highest" in sort_pref),
            )
        elif "Mana Value" in sort_pref:
            cards.sort(
                key=lambda x: (x.cmc or 0, x.name), reverse=("Highest" in sort_pref)
            )
        elif sort_pref == "Card Type":
            cards.sort(key=lambda x: (x.type_line or "", x.name))
        elif sort_pref == "Color Identity":
            cards.sort(
                key=lambda x: (
                    len(x.colors or ""),
                    c_order.get(x.colors[0] if x.colors else "", 7),
                    x.name,
                )
            )
        else:
            cards.sort(key=lambda x: (x.set_code, natural_key(x.collector_number)))

        cols = st.columns(6)
        for idx, card in enumerate(cards):
            with cols[idx % 6]:
                st.image(card.image_url if card.image_url else PLACEHOLDER_IMG)
                st.write(f"**{card.name}**")
                p_disp = (
                    f"${card.current_price:,.2f}" if card.current_price > 0 else "N/A"
                )
                st.caption(
                    f"#{card.collector_number} ({card.set_code.upper()}) | {p_disp}"
                )

    elif page == "Deck Builder":
        st.title("⚒️ Deck Builder")
        if "deck_draft" not in st.session_state:
            st.session_state.deck_draft = []
        d_name = st.text_input("New Deck Name")
        c1, c2 = st.columns([2, 1])
        with c1:
            find = st.text_input("Add Card")
            if find:
                res = session.exec(
                    select(Card).where(col(Card.name).ilike(f"%{find}%"))
                ).all()
                for c in res:
                    d_qty = sum(
                        i.quantity
                        for i in c.inventory_items
                        if i.location_type == "Drawer"
                    )
                    if st.button(f"Add {c.name} ({d_qty})", key=f"ad_{c.id}"):
                        inv = session.exec(
                            select(Inventory).where(
                                Inventory.card_id == c.id,
                                Inventory.location_type == "Drawer",
                            )
                        ).first()
                        if inv:
                            st.session_state.deck_draft.append(
                                {
                                    "id": c.id,
                                    "name": c.name,
                                    "drawer": inv.drawer,
                                    "pos": inv.position,
                                }
                            )
                            st.rerun()
        with c2:
            st.subheader("Pull List")
            st.session_state.deck_draft.sort(key=lambda x: (x["drawer"], x["pos"]))
            for e in st.session_state.deck_draft:
                st.write(f"D{e['drawer']} P{e['pos']} | {e['name']}")
            if st.button("Commit Pull") and d_name:
                for e in st.session_state.deck_draft:
                    inv = session.exec(
                        select(Inventory).where(
                            Inventory.card_id == e["id"],
                            Inventory.location_type == "Drawer",
                        )
                    ).first()
                    if inv:
                        remove_inventory_item(inv.id, 1, "DECK_PULL")
                        session.add(
                            Inventory(
                                card_id=e["id"],
                                location_type="Commander Deck",
                                section=d_name,
                                quantity=1,
                                is_placed=True,
                            )
                        )
                session.commit()
                st.session_state.deck_draft = []
                st.success("Deck Committed!")
                st.rerun()

    elif page == "System Logs":
        st.title("📂 System Logs")
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                log_data = f.readlines()
            st.code("".join(log_data[-50:]))
            if st.button("Clear Logs"):
                open(LOG_FILE, "w").close()
                st.rerun()

    elif page == "Physical Audit":
        st.title("🔍 Audit Mode")
        d_audit = st.selectbox("Select Drawer", range(1, 7))
        items = session.exec(
            select(Inventory)
            .where(Inventory.drawer == d_audit)
            .order_by(Inventory.position)
        ).all()
        if items:
            if (
                "audit_idx" not in st.session_state
                or st.session_state.get("curr_d") != d_audit
            ):
                st.session_state.audit_idx = 0
                st.session_state.curr_d = d_audit
            idx = st.session_state.audit_idx
            if idx < len(items):
                item = items[idx]
                st.progress(idx / len(items))
                cl1, cl2 = st.columns([1, 2])
                with cl1:
                    st.image(item.card.image_url)
                with cl2:
                    st.write(f"### {item.card.name}")
                    st.write(f"Pos {item.position} | #{item.card.collector_number}")
                    if st.button("✅ Next"):
                        st.session_state.audit_idx += 1
                        st.rerun()
                    if st.button("❌ Error"):
                        item.is_placed = False
                        session.commit()
                        st.session_state.audit_idx += 1
                        st.rerun()
            else:
                st.success("Audit complete!")
                if st.button("Restart"):
                    st.session_state.audit_idx = 0
                    st.rerun()

    elif page == "Commander Decks":
        st.title("⚔️ Decks")
        c_items = session.exec(
            select(Inventory).where(Inventory.location_type == "Commander Deck")
        ).all()
        for d in sorted(list(set([it.section for it in c_items if it.section]))):
            cur = [it for it in c_items if it.section == d]
            val = sum((it.card.current_price or 0) * it.quantity for it in cur)
            with st.expander(f"{d} - Value: ${val:,.2f}"):
                cls = st.columns(6)
                for i, inv in enumerate(cur):
                    with cls[i % 6]:
                        st.image(inv.card.image_url)
                        st.caption(inv.card.name)

    elif page == "Transaction History":
        st.title("📜 Logs")
        logs = session.exec(
            select(TransactionLog).order_by(desc(TransactionLog.timestamp))
        ).all()
        st.dataframe(
            pd.DataFrame([log.model_dump() for log in logs]), use_container_width=True
        )

    elif page == "Physical Drawer Map":
        st.title("📂 Map")
        for d in range(1, 7):
            items = session.exec(
                select(Inventory)
                .where(Inventory.drawer == d)
                .order_by(Inventory.position)
            ).all()
            with st.expander(f"Drawer {d}"):
                cls = st.columns(6)
                for i, inv in enumerate(items):
                    with cls[i % 6]:
                        if not inv.is_placed:
                            st.warning("PENDING")
                        st.image(inv.card.image_url)
                        st.caption(f"P{inv.position}: #{inv.card.collector_number}")

    elif page == "Data Import":
        st.title("📥 Import")
        it = st.selectbox("Dest", ["Drawer", "Deck"])
        dn = st.text_input("Deck Name") if it == "Deck" else None
        uf = st.file_uploader("CSV", type=["csv"])
        if uf and st.button("Run"):
            run_import(uf, "Drawer" if it == "Drawer" else "Commander Deck", dn)

    elif page == "Fuzzy Lookup":
        st.title("🔍 Scryfall")
        q = st.text_input("Card Name")
        if q:
            res = requests.get(f"https://api.scryfall.com/cards/named?fuzzy={q}")
            if res.status_code == 200:
                dt = res.json()
                cx1, cx2 = st.columns([1, 2])
                with cx1:
                    st.image(dt.get("image_uris", {}).get("normal", PLACEHOLDER_IMG))
                with cx2:
                    st.write(f"## {dt['name']}")
                    st.write(
                        f"**Set:** {dt['set'].upper()} | **Price:** ${dt.get('prices', {}).get('usd', 'N/A')}"
                    )
