from sqlalchemy.orm import Session

from app.inventory_service import get_owned_cards_by_set
from app.scryfall import fetch_set_cards


def get_set_completion(session: Session, set_code: str) -> dict:
    set_cards = fetch_set_cards(set_code)
    owned_map = get_owned_cards_by_set(session, set_code)

    total_cards = len(set_cards)
    owned_cards = 0
    missing_cards = []

    for card in set_cards:
        collector_number = card["collector_number"]

        if collector_number in owned_map:
            owned_cards += 1
        else:
            missing_cards.append(card)

    completion_pct = round((owned_cards / total_cards) * 100, 2) if total_cards > 0 else 0

    return {
        "set_code": set_code,
        "total_cards": total_cards,
        "owned_cards": owned_cards,
        "completion_pct": completion_pct,
        "missing_cards": missing_cards,
    }
