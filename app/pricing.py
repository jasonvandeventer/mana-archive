"""Pricing helpers.

Prices are stored as strings because they arrive from Scryfall as string-like
JSON values. The rest of the app should consume normalized floats.
"""

from __future__ import annotations

from app.models import Card


def parse_price(value: str | None) -> float:
    """Parse a nullable price string into a safe float."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def effective_price(card: Card, finish: str) -> float:
    """Return the best price for a card finish with sensible fallbacks."""
    finish = (finish or "normal").strip().lower()

    if finish == "foil":
        return parse_price(card.price_usd_foil) or parse_price(card.price_usd)

    if finish == "etched":
        return (
            parse_price(card.price_usd_etched)
            or parse_price(card.price_usd_foil)
            or parse_price(card.price_usd)
        )

    return parse_price(card.price_usd)
