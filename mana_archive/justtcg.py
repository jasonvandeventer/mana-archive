"""
JustTCG API client for card pricing.

Fetches current market prices from JustTCG (updated every 6 hours). Requires
JUSTTCG_API_KEY in the environment. Falls back to Scryfall prices when the key
is missing or requests fail.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

from mana_archive.logging_config import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.justtcg.com/v1"
DEFAULT_CONDITION = "NM"
REQUEST_DELAY = 6.5  # free tier supports 10 requests / minute
BATCH_SIZE = 20  # maximize cards per request on the free tier
MAX_RETRIES = 3
BACKOFF_SECONDS = 15.0
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "ManaArchive/1.0 (personal-collection-tool)"})


def _get_api_key() -> str | None:
    """Return the JustTCG API key from environment, or None if not set."""
    return os.environ.get("JUSTTCG_API_KEY", "").strip() or None


def _parse_variants(variants: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """
    Extract Normal and Foil prices from variant list.

    Returns (price_usd, price_usd_foil). Chooses the highest matching price per
    printing type to avoid response-order dependence.
    """
    normal_prices: list[float] = []
    foil_prices: list[float] = []
    for v in variants:
        p = v.get("price")
        if p is None:
            continue
        try:
            price_val = float(p)
        except (TypeError, ValueError):
            continue
        printing = (v.get("printing") or "").strip().lower()
        if "foil" in printing or printing == "foil":
            foil_prices.append(price_val)
        else:
            normal_prices.append(price_val)
    return (
        max(normal_prices) if normal_prices else None,
        max(foil_prices) if foil_prices else None,
    )


def fetch_prices_by_scryfall_ids(
    scryfall_ids: list[str],
    progress_callback=None,
) -> dict[str, dict[str, float | None]]:
    """
    Batch-fetch prices from JustTCG for the given Scryfall IDs.

    Parameters
    ----------
    scryfall_ids      : List of Scryfall UUIDs.
    progress_callback : Optional callable(processed_count, total) for UI.

    Returns
    -------
    dict mapping scryfall_id -> {"price_usd": float|None, "price_usd_foil": float|None}.
    Missing or failed lookups are omitted.
    """
    api_key = _get_api_key()
    if not api_key:
        log.debug("JUSTTCG_API_KEY not set; skipping JustTCG price fetch.")
        return {}

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    result: dict[str, dict[str, float | None]] = {}
    total = len(scryfall_ids)

    for i in range(0, total, BATCH_SIZE):
        chunk = scryfall_ids[i : i + BATCH_SIZE]
        payload = [{"scryfallId": sid, "condition": DEFAULT_CONDITION} for sid in chunk]
        data: dict[str, Any] | None = None

        for attempt in range(MAX_RETRIES):
            try:
                resp = SESSION.post(
                    f"{BASE_URL}/cards",
                    json=payload,
                    headers=headers,
                    timeout=15,
                )

                if resp.status_code == 429:
                    if attempt < MAX_RETRIES - 1:
                        sleep_time = BACKOFF_SECONDS * (attempt + 1)
                        log.warning(
                            "JustTCG rate limit hit for batch starting at %d. Retrying in %.1fs.",
                            i,
                            sleep_time,
                        )
                        time.sleep(sleep_time)
                        continue
                    log.warning("JustTCG batch request failed after retries: 429 Too Many Requests")
                    break

                resp.raise_for_status()
                data = resp.json()
                break
            except requests.RequestException as exc:
                if attempt < MAX_RETRIES - 1:
                    sleep_time = BACKOFF_SECONDS * (attempt + 1)
                    log.warning(
                        "JustTCG batch request failed (attempt %d/%d): %s. Retrying in %.1fs.",
                        attempt + 1,
                        MAX_RETRIES,
                        exc,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
                else:
                    log.warning("JustTCG batch request failed after retries: %s", exc)

        # Respect published per-minute limits even after successful requests.
        time.sleep(REQUEST_DELAY)

        if not data:
            continue

        cards = data.get("data", [])
        returned_ids = set()
        for card in cards:
            sid = card.get("scryfallId")
            if not sid:
                continue
            returned_ids.add(sid)
            variants = card.get("variants", [])
            price_usd, price_usd_foil = _parse_variants(variants)
            result[sid] = {"price_usd": price_usd, "price_usd_foil": price_usd_foil}

        missing_ids = set(chunk) - returned_ids
        if missing_ids:
            log.warning(
                "JustTCG returned no price payload for %d card(s) in current batch.",
                len(missing_ids),
            )

        if progress_callback:
            processed = min(i + BATCH_SIZE, total)
            progress_callback(processed, total)

    return result


def merge_prices_into_card_data(
    card_data: dict[str, Any],
    prices: dict[str, dict[str, float | None]],
) -> None:
    """
    Mutate card_data in place, overwriting price_usd and price_usd_foil
    with values from the JustTCG prices dict when available.
    """
    sid = card_data.get("scryfall_id")
    if not sid or sid not in prices:
        return
    p = prices[sid]
    if p.get("price_usd") is not None:
        card_data["price_usd"] = p["price_usd"]
    if p.get("price_usd_foil") is not None:
        card_data["price_usd_foil"] = p["price_usd_foil"]
