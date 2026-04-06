"""Finish-aware price helpers."""
from __future__ import annotations

from typing import Any

from mana_archive.models import Finish


def get_price_for_finish(card_like: dict[str, Any], finish: Finish | str | None) -> float | None:
    """Return the best available price for the requested finish."""
    if finish is None:
        finish_value = "nonfoil"
    elif isinstance(finish, Finish):
        finish_value = finish.value
    else:
        finish_value = str(finish).strip().lower() or "nonfoil"

    normal = card_like.get("price_usd")
    foil = card_like.get("price_usd_foil")
    etched = card_like.get("price_usd_etched")

    if finish_value == "etched":
        return etched if etched is not None else (foil if foil is not None else normal)
    if finish_value == "foil":
        return foil if foil is not None else normal
    return normal
