"""
Mana-Archive – Physical MTG Inventory Management System
Entry point: run with `streamlit run app.py`
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

from mana_archive.database import init_db
from mana_archive.logging_config import configure_logging, get_logger
from mana_archive.pages import (
    audit_log,
    browse_collection,
    deck_builder,
    drawers,
    import_cards,
    pending_placement,
)

# Configure logging once per process
configure_logging()
log = get_logger(__name__)

st.set_page_config(
    page_title="Mana-Archive",
    page_icon="🗃️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialise database tables (idempotent)
init_db()


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
PAGES = {
    "📥 Import Cards": import_cards,
    "⏳ Pending Placement": pending_placement,
    "🗂️ Drawers": drawers,
    "🔍 Browse Collection": browse_collection,
    "🃏 Deck Builder": deck_builder,
    "📋 Audit Log": audit_log,
}

st.sidebar.title("🗃️ Mana-Archive")
st.sidebar.caption("Physical MTG Collection Manager")
st.sidebar.divider()

selection = st.sidebar.radio("Navigate", list(PAGES.keys()), label_visibility="collapsed")

st.sidebar.divider()
st.sidebar.markdown(
    """
    **Drawer Map**
    | # | Contents |
    |---|----------|
    | 1 | Value ($5+) |
    | 2 | Sets A – D |
    | 3 | Sets E – L |
    | 4 | Sets M – R |
    | 5 | Sets S – Z |
    | 6 | Non-alpha sets |
    """
)

# ---------------------------------------------------------------------------
# Render selected page
# ---------------------------------------------------------------------------
PAGES[selection].render()
