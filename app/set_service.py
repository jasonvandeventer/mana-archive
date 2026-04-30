from __future__ import annotations

from sqlalchemy.orm import Session

from app.inventory_service import get_owned_cards_by_set, list_owned_sets
from app.scryfall import fetch_set_cards


def get_set_completion(
    session: Session,
    set_code: str,
    user_id: int,
    view: str = "all",
) -> dict:
    """Build set-completion data for one user's collection.

    Scryfall set/card metadata is global, but ownership counts must always be
    scoped to the current user.
    """
    set_code = (set_code or "").strip().lower()
    view = view if view in {"all", "owned", "missing"} else "all"

    set_cards = fetch_set_cards(set_code)
    owned_map = get_owned_cards_by_set(session, set_code=set_code, user_id=user_id)

    owned_cards_list = []
    missing_cards = []

    for card in set_cards:
        collector_number = card["collector_number"]
        quantity_owned = owned_map.get(collector_number, 0)
        card["quantity_owned"] = quantity_owned

        if quantity_owned > 0:
            owned_cards_list.append(card)
        else:
            missing_cards.append(card)

    total_cards = len(set_cards)
    owned_cards = len(owned_cards_list)
    completion_pct = round((owned_cards / total_cards) * 100, 2) if total_cards else 0

    visible_cards = set_cards
    if view == "owned":
        visible_cards = owned_cards_list
    elif view == "missing":
        visible_cards = missing_cards

    return {
        "set_code": set_code,
        "set_name": set_cards[0]["set_name"] if set_cards else set_code.upper(),
        "total_cards": total_cards,
        "owned_cards": owned_cards,
        "completion_pct": completion_pct,
        "owned_cards_list": owned_cards_list,
        "missing_cards": missing_cards,
        "visible_cards": visible_cards,
        "view": view,
    }


def list_set_completion_summaries(session: Session, user_id: int) -> list[dict]:
    """Build set-completion summaries for one user's owned sets."""
    owned_sets = list_owned_sets(session, user_id=user_id)
    summaries = []

    for owned_set in owned_sets:
        set_code = owned_set["set_code"]
        set_cards = fetch_set_cards(set_code)
        owned_map = get_owned_cards_by_set(session, set_code=set_code, user_id=user_id)

        total_cards = len(set_cards)
        owned_cards = sum(1 for card in set_cards if owned_map.get(card["collector_number"], 0) > 0)
        missing_count = max(total_cards - owned_cards, 0)
        completion_pct = round((owned_cards / total_cards) * 100, 2) if total_cards else 0

        summaries.append(
            {
                "set_code": set_code,
                "set_name": owned_set["set_name"],
                "unique_owned": owned_set["unique_owned"],
                "total_cards": total_cards,
                "owned_cards": owned_cards,
                "missing_count": missing_count,
                "completion_pct": completion_pct,
            }
        )

    summaries.sort(key=lambda s: (-s["completion_pct"], s["set_code"]))
    return summaries
