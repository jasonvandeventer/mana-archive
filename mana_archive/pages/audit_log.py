"""Audit Log page – view TransactionLog history."""
from __future__ import annotations

import streamlit as st
from sqlmodel import Session, select

from mana_archive.database import get_engine
from mana_archive.logging_config import get_logger
from mana_archive.models import Card, TransactionKind, TransactionLog

log = get_logger(__name__)

KIND_ICONS = {
    TransactionKind.IMPORT: "📥",
    TransactionKind.PLACEMENT_CONFIRMED: "✅",
    TransactionKind.PULL: "🃏",
    TransactionKind.MOVE: "📦",
    TransactionKind.QUANTITY_UPDATE: "🔢",
}

PAGE_SIZE = 100


def _load_log(kind_filter: str, search: str, page: int) -> tuple[list[dict], int]:
    with Session(get_engine()) as session:
        stmt = (
            select(TransactionLog, Card)
            .join(Card, TransactionLog.card_id == Card.id)
        )
        if kind_filter != "All":
            stmt = stmt.where(TransactionLog.kind == TransactionKind(kind_filter.lower()))
        if search:
            stmt = stmt.where(
                Card.name.icontains(search)
            )

        from sqlalchemy import func
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.exec(count_stmt).one()

        stmt = (
            stmt
            .order_by(TransactionLog.timestamp.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
        rows = session.exec(stmt).all()

        return [
            {
                "id": tx.id,
                "timestamp": tx.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "kind": tx.kind.value,
                "card_name": card.name,
                "detail": tx.detail or "",
                "old_drawer": tx.old_drawer,
                "new_drawer": tx.new_drawer,
                "old_position": tx.old_position,
                "new_position": tx.new_position,
                "qty_delta": tx.quantity_delta,
            }
            for tx, card in rows
        ], total


def render() -> None:
    st.header("Audit Log")
    st.caption("Immutable record of all imports, placements, pulls, and moves.")

    col1, col2, col3 = st.columns([2, 3, 1])
    with col1:
        kind_options = ["All"] + [k.value.replace("_", " ").title() for k in TransactionKind]
        kind_filter = st.selectbox("Event Type", kind_options)
        # Map title-cased back for query
        if kind_filter != "All":
            kind_filter = kind_filter.replace(" ", "_").lower()
            try:
                kind_filter = TransactionKind(kind_filter).value.replace("_", " ").title()
            except ValueError:
                kind_filter = "All"
    with col2:
        search = st.text_input("Search card name", placeholder="Lightning Bolt")
    with col3:
        page = st.number_input("Page", min_value=1, value=1, step=1)

    # Re-map kind filter for query
    query_kind = kind_filter
    if kind_filter != "All":
        query_kind = kind_filter.replace(" ", "_").lower()
        # Map to TransactionKind value
        query_kind_mapped = None
        for k in TransactionKind:
            if k.value == query_kind or k.name.lower() == query_kind:
                query_kind_mapped = k.value.replace("_", " ").title()
                break
        query_kind = query_kind_mapped or "All"

    rows, total = _load_log(query_kind, search, page)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.caption(f"Page {page} / {total_pages}  ({total} events total)")

    if not rows:
        st.info("No log entries found.")
        return

    for row in rows:
        kind_val = row["kind"]
        icon = "📋"
        for k, ico in KIND_ICONS.items():
            if k.value == kind_val:
                icon = ico
                break

        drawer_info = ""
        if row["old_drawer"] is not None and row["new_drawer"] is not None:
            drawer_info = f"  ·  Drawer {row['old_drawer']} → {row['new_drawer']}"
        elif row["new_drawer"] is not None:
            drawer_info = f"  ·  → Drawer {row['new_drawer']}"

        qty_info = ""
        if row["qty_delta"] is not None and row["qty_delta"] != 0:
            sign = "+" if row["qty_delta"] > 0 else ""
            qty_info = f"  ·  Qty {sign}{row['qty_delta']}"

        st.markdown(
            f"{icon} `{row['timestamp']}`  **{row['card_name']}**  "
            f"— *{kind_val.replace('_', ' ').title()}*  "
            f"{drawer_info}{qty_info}  \n"
            f"<small>{row['detail']}</small>",
            unsafe_allow_html=True,
        )
        st.divider()
