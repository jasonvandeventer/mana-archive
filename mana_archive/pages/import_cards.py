"""Import Cards page – CSV upload or manual single-card entry."""
from __future__ import annotations

import csv
import io

import streamlit as st

from mana_archive.database import get_session
from mana_archive.inventory_service import import_from_csv, import_single_card, undo_last_import
from mana_archive.logging_config import get_logger
from mana_archive.models import Finish
from mana_archive.pricing import get_price_for_finish
from mana_archive.justtcg import fetch_prices_by_scryfall_ids, merge_prices_into_card_data
from mana_archive.scryfall import (
    fetch_by_name,
    fetch_by_scryfall_id,
    fetch_by_set_collector,
    fetch_collection,
    parse_card_data,
)

log = get_logger(__name__)

DRAWER_LABELS = {
    1: "Drawer 1 – Value ($5+)",
    2: "Drawer 2 – Sets A–D",
    3: "Drawer 3 – Sets E–L",
    4: "Drawer 4 – Sets M–R",
    5: "Drawer 5 – Sets S–Z",
    6: "Drawer 6 – Non-alpha sets (2x2, etc.)",
}


def _scryfall_fetch(identifier: dict) -> dict | None:
    """Resolve a single identifier dict to parsed card data."""
    raw = None
    if "id" in identifier:
        raw = fetch_by_scryfall_id(identifier["id"])
    elif "name" in identifier:
        raw = fetch_by_name(identifier["name"], identifier.get("set"))
    if raw is None:
        return None
    return parse_card_data(raw)


def _build_batch_fetch_fn(csv_content: str):
    """
    Return a fetch function pre-loaded with a bulk Scryfall lookup.

    Rows that carry a Scryfall ID are fetched in one /cards/collection call
    (up to 75 per request).  Rows with only a name fall back to the individual
    fuzzy endpoint.  This eliminates wrong-card fuzzy matches for well-formed
    CSVs and is dramatically faster than one request per row.
    """
    # Parse the CSV and normalise header keys
    reader = csv.DictReader(io.StringIO(csv_content))
    rows = [
        {k.strip().lower().replace(" ", "_").replace("-", "_"): v.strip()
         for k, v in row.items()}
        for row in reader
    ]

    # Split rows: those with a valid Scryfall ID go to the batch endpoint
    batch_ids: list[str] = []
    for row in rows:
        sid = row.get("scryfall_id", "")
        if sid:
            batch_ids.append(sid)

    # Pre-fetch all batch IDs in one (or a few) calls
    cache: dict[str, dict] = {}
    if batch_ids:
        identifiers = [{"id": sid} for sid in batch_ids]
        raw_cards = fetch_collection(identifiers)
        for raw in raw_cards:
            parsed = parse_card_data(raw)
            cache[parsed["scryfall_id"]] = parsed

    def fetch_fn(identifier: dict) -> dict | None:
        if "id" in identifier:
            # Try the pre-populated cache first, then fall back to a live call
            if identifier["id"] in cache:
                return cache[identifier["id"]]
            raw = fetch_by_scryfall_id(identifier["id"])
            return parse_card_data(raw) if raw else None
        if "name" in identifier:
            raw = fetch_by_name(identifier["name"], identifier.get("set"))
            return parse_card_data(raw) if raw else None
        return None

    return fetch_fn


def render() -> None:
    st.header("Import Cards")

    tab_csv, tab_manual, tab_batch = st.tabs(["CSV Upload", "Manual Entry", "Batch by Name"])

    # ------------------------------------------------------------------
    # CSV Upload
    # ------------------------------------------------------------------
    with tab_csv:
        st.markdown(
            """
            Upload a CSV file. Required columns: **name** or **Scryfall ID**.
            Optional columns: `Set code`, `Collector number`, `quantity`,
            `finish` (`nonfoil` / `foil` / `etched`).

            Column names are case-insensitive and spaces or hyphens are treated
            as underscores, so `Scryfall ID`, `scryfall_id`, and `scryfall id`
            are all accepted.  When a **Scryfall ID** is present, cards are
            fetched in bulk (up to 75 at a time) — no fuzzy name matching.
            """
        )
        uploaded = st.file_uploader("Choose CSV file", type=["csv"])

        if uploaded is not None:
            csv_content = uploaded.read().decode("utf-8")
            line_count = csv_content.count("\n")
            st.info(f"File loaded – approximately {line_count} rows detected.")

            if st.button("Import CSV", key="btn_import_csv", type="primary"):
                progress_bar = st.progress(0, text="Pre-fetching card data from Scryfall…")
                status_placeholder = st.empty()
                results: list[dict] = []

                with st.spinner("Fetching card data from Scryfall (batch)…"):
                    fetch_fn = _build_batch_fetch_fn(csv_content)

                progress_bar.progress(0, text="Starting import…")

                def _progress(current: int, total: int, name: str) -> None:
                    pct = int((current / total) * 100)
                    progress_bar.progress(pct, text=f"[{current}/{total}] {name}")
                    status_placeholder.caption(f"Processing: {name}")

                with get_session() as session:
                    results = import_from_csv(
                        session,
                        csv_content,
                        fetch_fn,
                        progress_callback=_progress,
                    )

                progress_bar.progress(100, text="Done!")
                status_placeholder.empty()

                ok_count = sum(1 for r in results if r["status"] == "ok")
                err_count = len(results) - ok_count
                st.success(f"Import complete: {ok_count} imported, {err_count} errors.")

                if err_count:
                    with st.expander("Show errors"):
                        for r in results:
                            if r["status"] == "error":
                                st.error(f"**{r['name']}** – {r['detail']}")

                with st.expander("Full import log"):
                    for r in results:
                        icon = "✅" if r["status"] == "ok" else "❌"
                        st.write(f"{icon} **{r['name']}** – {r['detail']}")

    # ------------------------------------------------------------------
    # Manual Entry / Scan
    # ------------------------------------------------------------------
    with tab_manual:
        # Undo bar – always visible at the top of the tab
        undo_col, undo_spacer = st.columns([2, 6])
        with undo_col:
            if st.button("↩ Undo Last Scan", key="btn_undo_scan"):
                try:
                    with get_session() as session:
                        result = undo_last_import(session)
                    verb = "Removed" if result["deleted"] else "Decremented"
                    st.success(
                        f"{verb} **{result['quantity']}×** **{result['card_name']}** "
                        f"from {DRAWER_LABELS[result['drawer']]}."
                    )
                    # Clear any previewed card so the form is clean
                    st.session_state.pop("manual_card_data", None)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        st.divider()

        # Lookup priority:
        #   1. Set Code + Collector Number  ← most precise; use when scanning
        #   2. Scryfall UUID
        #   3. Card Name (fuzzy)
        st.markdown(
            "**Primary:** Set Code + Collector Number (e.g. `pza` + `006`)  \n"
            "**Fallback:** Card Name or Scryfall UUID"
        )

        lc, rc = st.columns(2)
        with lc:
            scan_set = st.text_input(
                "Set Code", placeholder="pza", key="scan_set"
            )
            scan_collector = st.text_input(
                "Collector Number", placeholder="006", key="scan_collector"
            )
            card_name = st.text_input(
                "Card Name (if no set/collector)", placeholder="Lightning Bolt",
                key="scan_name",
            )
        with rc:
            scryfall_id = st.text_input(
                "Scryfall ID (optional, overrides all)", key="scan_scryfall_id"
            )
            finish = st.selectbox("Finish", [f.value for f in Finish], key="scan_finish")
            quantity = st.number_input(
                "Quantity", min_value=1, max_value=100, value=1, key="scan_qty"
            )

        if st.button("Look Up Card", key="btn_manual_lookup", type="primary"):
            raw = None
            with st.spinner("Fetching from Scryfall…"):
                if scryfall_id.strip():
                    raw = fetch_by_scryfall_id(scryfall_id.strip())
                elif scan_set.strip() and scan_collector.strip():
                    raw = fetch_by_set_collector(scan_set.strip(), scan_collector.strip())
                elif card_name.strip():
                    raw = fetch_by_name(card_name.strip(), scan_set.strip() or None)

            if raw is None:
                st.error(
                    "Card not found on Scryfall. "
                    "Check the set code and collector number, or try the card name."
                )
                st.session_state.pop("manual_card_data", None)
            else:
                card_data = parse_card_data(raw)
                prices, _missing_ids, _failed_ids = fetch_prices_by_scryfall_ids([card_data["scryfall_id"]])
                merge_prices_into_card_data(card_data, prices)
                st.session_state["manual_card_data"] = card_data

        # Show preview + Confirm whenever a card is stored in state
        card_data = st.session_state.get("manual_card_data")
        if card_data:
            st.divider()
            col_img, col_info = st.columns([1, 2])
            with col_img:
                if card_data.get("image_uri"):
                    st.image(card_data["image_uri"], width=220)
            with col_info:
                st.subheader(card_data["name"])
                st.write(
                    f"**Set:** {card_data['set_name']} "
                    f"({card_data['set_code'].upper()} #{card_data['collector_number']})"
                )
                st.write(f"**Type:** {card_data['type_line']}")
                selected_finish = Finish(finish)
                price_display = get_price_for_finish(card_data, selected_finish)
                st.write(
                    f"**Price:** ${price_display:.2f}" if price_display is not None else "**Price:** N/A"
                )

                if st.button("✅ Confirm Import", key="btn_confirm_manual", type="primary"):
                    with get_session() as session:
                        inv, _tx = import_single_card(
                            session,
                            card_data,
                            Finish(finish),
                            quantity,
                        )
                        # Read scalar values before the session closes and
                        # expires all attributes (expire_on_commit=True default).
                        inv_drawer = inv.drawer
                        inv_position = inv.position
                    drawer_label = DRAWER_LABELS[inv_drawer]
                    st.success(
                        f"Imported **{card_data['name']}** → {drawer_label}, "
                        f"position {inv_position}. Pending placement."
                    )
                    # Clear state so the form is ready for the next scan
                    st.session_state.pop("manual_card_data", None)
                    st.rerun()

    # ------------------------------------------------------------------
    # Batch by Name
    # ------------------------------------------------------------------
    with tab_batch:
        st.markdown(
            "Paste card names (one per line). Optionally append `|<set_code>` or `|<set_code>|<finish>`."
        )
        raw_text = st.text_area(
            "Card list",
            height=200,
            placeholder="Lightning Bolt\nBlack Lotus|lea\nTime Walk|lea|nonfoil",
        )
        batch_finish = st.selectbox("Default Finish", [f.value for f in Finish], key="batch_finish")

        if st.button("Import Batch", key="btn_batch_import", type="primary"):
            lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
            if not lines:
                st.warning("No card names entered.")
            else:
                # Build identifiers for collection fetch
                identifiers = []
                per_line_meta: list[dict] = []
                for line in lines:
                    parts = line.split("|")
                    name = parts[0].strip()
                    s_code = parts[1].strip() if len(parts) > 1 else None
                    fin_val = parts[2].strip() if len(parts) > 2 else batch_finish
                    try:
                        fin = Finish(fin_val)
                    except ValueError:
                        fin = Finish(batch_finish)
                    ident = {"name": name}
                    if s_code:
                        ident["set"] = s_code
                    identifiers.append(ident)
                    per_line_meta.append({"name": name, "finish": fin})

                with st.spinner(f"Fetching {len(identifiers)} cards from Scryfall…"):
                    raw_cards = fetch_collection(identifiers)
                    parsed = {parse_card_data(r)["name"].lower(): parse_card_data(r) for r in raw_cards}

                # Enrich with JustTCG prices
                if parsed:
                    ids = [c["scryfall_id"] for c in parsed.values()]
                    prices, _missing_ids, _failed_ids = fetch_prices_by_scryfall_ids(ids)
                    for card_data in parsed.values():
                        merge_prices_into_card_data(card_data, prices)

                results = []
                with get_session() as session:
                    for meta in per_line_meta:
                        card_data = parsed.get(meta["name"].lower())
                        if card_data is None:
                            results.append(
                                {"name": meta["name"], "status": "error", "detail": "Not found on Scryfall"}
                            )
                            continue
                        try:
                            inv, _tx = import_single_card(session, card_data, meta["finish"], 1)
                            results.append(
                                {
                                    "name": card_data["name"],
                                    "status": "ok",
                                    "detail": f"Drawer {inv.drawer}, pos {inv.position}",
                                }
                            )
                        except Exception as exc:
                            results.append({"name": meta["name"], "status": "error", "detail": str(exc)})

                ok = sum(1 for r in results if r["status"] == "ok")
                st.success(f"Batch import: {ok}/{len(results)} successful.")
                for r in results:
                    icon = "✅" if r["status"] == "ok" else "❌"
                    st.write(f"{icon} **{r['name']}** – {r['detail']}")
