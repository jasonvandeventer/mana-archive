"""
Scryfall API client.

Provides helpers to look up card data by Scryfall ID, exact name, or a batch
of identifiers. Respects Scryfall's rate-limit guidelines (50-100 ms delay
between requests; 75 ms used here).
"""
from __future__ import annotations

import time
from typing import Any

import requests

from mana_archive.logging_config import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.scryfall.com"
REQUEST_DELAY = 0.1  # seconds between requests per Scryfall guidelines
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ManaArchive/1.0 (personal-collection-tool)"})


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _get(path: str, params: dict | None = None) -> dict[str, Any]:
    """Perform a GET request and return the parsed JSON body."""
    url = f"{BASE_URL}{path}"
    response = SESSION.get(url, params=params, timeout=10)
    time.sleep(REQUEST_DELAY)
    response.raise_for_status()
    return response.json()


def _post(path: str, payload: dict) -> dict[str, Any]:
    """Perform a POST request and return the parsed JSON body."""
    url = f"{BASE_URL}{path}"
    response = SESSION.post(url, json=payload, timeout=30)
    time.sleep(REQUEST_DELAY)
    response.raise_for_status()
    return response.json()




def _to_float(value: Any) -> float | None:
    """Convert API price strings to floats while preserving missing values."""
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_by_scryfall_id(scryfall_id: str) -> dict[str, Any] | None:
    """
    Return the Scryfall card object for the given UUID, or None on failure.
    """
    try:
        return _get(f"/cards/{scryfall_id}")
    except requests.HTTPError as exc:
        log.warning("Scryfall lookup failed for id=%s: %s", scryfall_id, exc)
        return None


def fetch_by_set_collector(
    set_code: str,
    collector_number: str,
) -> dict[str, Any] | None:
    """
    Return a Scryfall card object using the exact set code + collector number.

    This is the most precise lookup — equivalent to scanning a card's set symbol
    and collector number (e.g. "pza" + "006").  Collector numbers may include
    letters (e.g. "6a", "★1").
    """
    try:
        return _get(f"/cards/{set_code.lower()}/{collector_number}")
    except requests.HTTPError as exc:
        log.warning(
            "Scryfall set/collector lookup failed for %s/%s: %s",
            set_code,
            collector_number,
            exc,
        )
        return None


def fetch_by_name(
    name: str,
    set_code: str | None = None,
) -> dict[str, Any] | None:
    """
    Return a Scryfall card object using fuzzy name search.

    Parameters
    ----------
    name     : Card name (partial or full).
    set_code : Optional Scryfall set code to narrow results.
    """
    params: dict[str, str] = {"fuzzy": name}
    if set_code:
        params["set"] = set_code
    try:
        return _get("/cards/named", params=params)
    except requests.HTTPError as exc:
        log.warning(
            "Scryfall name lookup failed for name=%r set=%r: %s",
            name,
            set_code,
            exc,
        )
        return None


def fetch_collection(identifiers: list[dict[str, str]]) -> list[dict[str, Any]]:
    """
    Batch-fetch up to 75 cards using the Scryfall /cards/collection endpoint.

    Parameters
    ----------
    identifiers : List of identifier dicts, e.g. [{"id": "<uuid>"}, ...] or
                  [{"name": "Lightning Bolt"}, ...].

    Returns
    -------
    list : Scryfall card objects (not-found cards are omitted with a warning).
    """
    results: list[dict[str, Any]] = []
    chunk_size = 75

    for i in range(0, len(identifiers), chunk_size):
        chunk = identifiers[i : i + chunk_size]
        try:
            data = _post("/cards/collection", {"identifiers": chunk})
        except requests.HTTPError as exc:
            log.error("Scryfall collection batch failed: %s", exc)
            continue

        results.extend(data.get("data", []))

        not_found = data.get("not_found", [])
        if not_found:
            log.warning("Scryfall could not find %d card(s): %s", len(not_found), not_found)

    return results


def parse_card_data(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Extract and normalise the fields we care about from a raw Scryfall object.

    Handles both normal cards and dual-faced cards (uses front face for images
    and mana cost).
    """
    # For double-faced cards, prefer the first card_face for display fields
    faces = raw.get("card_faces", [])
    front = faces[0] if faces else raw

    image_uris = front.get("image_uris") or raw.get("image_uris") or {}
    colors = raw.get("colors") or front.get("colors") or []
    color_identity = raw.get("color_identity", [])

    prices = raw.get("prices", {})

    return {
        "scryfall_id": raw["id"],
        "name": raw["name"],
        "set_code": raw["set"],
        "set_name": raw.get("set_name", ""),
        "collector_number": raw.get("collector_number", ""),
        "rarity": raw.get("rarity", ""),
        "type_line": raw.get("type_line") or front.get("type_line", ""),
        "mana_cost": front.get("mana_cost"),
        "cmc": float(raw.get("cmc", 0)),
        "colors": "|".join(colors) if colors else None,
        "color_identity": "|".join(color_identity) if color_identity else None,
        "image_uri": image_uris.get("normal") or image_uris.get("large"),
        "price_usd": _to_float(prices.get("usd")),
        "price_usd_foil": _to_float(prices.get("usd_foil")),
        "price_usd_etched": _to_float(prices.get("usd_etched")),
        "oracle_text": front.get("oracle_text") or raw.get("oracle_text"),
    }
