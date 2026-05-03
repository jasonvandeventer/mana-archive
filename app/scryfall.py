"""Scryfall API integration.

This module owns HTTP retry/throttle behavior and normalization of Scryfall
responses into the Card model shape used by the rest of the app.
"""

from __future__ import annotations

import time
from datetime import datetime
from functools import lru_cache
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.models import Card

SCRYFALL_CARD_URL = "https://api.scryfall.com/cards"
HEADERS = {"User-Agent": "ManaArchive/1.0", "Accept": "application/json"}
REQUEST_DELAY_SECONDS = 0.08

_session = requests.Session()
_retry = Retry(
    total=4,
    connect=4,
    read=4,
    backoff_factor=0.6,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)
_adapter = HTTPAdapter(max_retries=_retry)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)
_last_request_at = 0.0


def _throttle() -> None:
    global _last_request_at
    now = time.monotonic()
    elapsed = now - _last_request_at
    if elapsed < REQUEST_DELAY_SECONDS:
        time.sleep(REQUEST_DELAY_SECONDS - elapsed)
    _last_request_at = time.monotonic()


def _normalize_card_payload(raw: dict[str, Any]) -> dict[str, Any]:
    image_uris = raw.get("image_uris") or {}
    prices = raw.get("prices") or {}
    card_faces = raw.get("card_faces") or []
    if not image_uris and card_faces:
        first_face = card_faces[0] or {}
        image_uris = first_face.get("image_uris") or {}

    oracle_text = raw.get("oracle_text")
    if not oracle_text and card_faces:
        oracle_text = "\n\n".join(
            face.get("oracle_text", "") for face in card_faces if face.get("oracle_text")
        )

    type_line = raw.get("type_line")
    if not type_line and card_faces:
        type_line = " // ".join(
            face.get("type_line", "") for face in card_faces if face.get("type_line")
        )

    return {
        "scryfall_id": raw.get("id"),
        "name": raw.get("name"),
        "set_code": raw.get("set"),
        "set_name": raw.get("set_name"),
        "collector_number": raw.get("collector_number"),
        "rarity": raw.get("rarity"),
        "image_url": image_uris.get("normal") or image_uris.get("large") or image_uris.get("small"),
        "type_line": type_line,
        "oracle_text": oracle_text,
        "price_usd": prices.get("usd"),
        "price_usd_foil": prices.get("usd_foil"),
        "price_usd_etched": prices.get("usd_etched"),
    }


def _get_json(url: str) -> dict[str, Any] | None:
    try:
        _throttle()
        response = _session.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


@lru_cache(maxsize=8192)
def _fetch_by_id_cached(scryfall_id: str) -> dict[str, Any] | None:
    scryfall_id = (scryfall_id or "").strip()
    if not scryfall_id:
        return None
    raw = _get_json(f"{SCRYFALL_CARD_URL}/{scryfall_id}")
    return _normalize_card_payload(raw) if raw else None


@lru_cache(maxsize=8192)
def _fetch_by_set_number_cached(set_code: str, collector_number: str) -> dict[str, Any] | None:
    set_code = (set_code or "").strip().lower()
    collector_number = (collector_number or "").strip()
    if not set_code or not collector_number:
        return None
    raw = _get_json(f"{SCRYFALL_CARD_URL}/{set_code}/{collector_number}")
    return _normalize_card_payload(raw) if raw else None


def fetch_card_by_scryfall_id(scryfall_id: str) -> dict[str, Any] | None:
    return _fetch_by_id_cached((scryfall_id or "").strip())


def fetch_card_by_set_and_number(set_code: str, collector_number: str) -> dict[str, Any] | None:
    collector_number = (collector_number or "").strip()
    if collector_number.endswith("*"):
        collector_number = collector_number[:-1].strip()
    return _fetch_by_set_number_cached((set_code or "").strip().lower(), collector_number)


def refresh_card_from_scryfall(session: Session, card_id: int) -> bool:
    card = session.query(Card).filter(Card.id == card_id).first()
    if not card:
        return False

    fresh = fetch_card_by_scryfall_id(card.scryfall_id)
    if not fresh:
        return False

    card.name = fresh["name"]
    card.set_code = fresh["set_code"]
    card.set_name = fresh["set_name"]
    card.collector_number = fresh["collector_number"]
    card.rarity = fresh["rarity"]
    card.image_url = fresh["image_url"]
    card.type_line = fresh["type_line"]
    card.oracle_text = fresh["oracle_text"]
    card.price_usd = fresh["price_usd"]
    card.price_usd_foil = fresh["price_usd_foil"]
    card.price_usd_etched = fresh["price_usd_etched"]
    card.updated_at = datetime.utcnow()
    session.commit()
    return True


@lru_cache(maxsize=4096)
def fetch_card_traits(scryfall_id: str) -> dict[str, bool] | None:
    scryfall_id = (scryfall_id or "").strip()
    if not scryfall_id:
        return None

    raw = _get_json(f"{SCRYFALL_CARD_URL}/{scryfall_id}")
    if not raw:
        return None

    type_line = (raw.get("type_line") or "").lower()
    card_faces = raw.get("card_faces") or []
    if not type_line and card_faces:
        type_line = " // ".join((face.get("type_line") or "") for face in card_faces).lower()

    return {
        "is_basic_land": "basic land" in type_line,
        "is_full_art": bool(raw.get("full_art")),
    }


def fetch_set_cards(set_code: str) -> list[dict[str, Any]]:
    set_code = (set_code or "").strip().lower()
    if not set_code:
        return []

    results = []
    url = f"https://api.scryfall.com/cards/search?q=e:{set_code}&unique=prints&order=set"

    while url:
        data = _get_json(url)
        if not data:
            break

        for card in data.get("data", []):
            normalized = _normalize_card_payload(card)
            results.append(normalized)

        if data.get("has_more"):
            url = data.get("next_page")
        else:
            url = None

    return results


def search_cards_by_name(name: str, limit: int = 20) -> list[dict[str, Any]]:
    query = name.strip()
    if not query:
        return []

    url = (
        "https://api.scryfall.com/cards/search"
        f'?q=!"{query}" or {query}&unique=prints&order=released&dir=desc'
    )

    data = _get_json(url)
    if not data:
        return []

    cards = data.get("data", [])

    return [
        {
            "id": card.get("id"),
            "name": card.get("name"),
            "set": card.get("set"),
            "set_name": card.get("set_name"),
            "collector_number": card.get("collector_number"),
            "rarity": card.get("rarity"),
            "image_uris": card.get("image_uris"),
            "card_faces": card.get("card_faces"),
            "prices": card.get("prices"),
        }
        for card in cards[:limit]
    ]
