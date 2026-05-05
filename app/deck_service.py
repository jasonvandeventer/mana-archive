from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.audit_service import log_transaction
from app.models import Card, Deck, InventoryRow, StorageLocation
from app.scryfall import fetch_deck_tokens

_RAMP_LAND_RE = re.compile(r"search your library for .{0,60}land", re.IGNORECASE)
_DRAW_RE = re.compile(
    r"\bdraw (?:a|an|x|\d+|two|three|four|five|six|that many) cards?\b", re.IGNORECASE
)
_REMOVAL_RE = re.compile(
    r"(?:destroy|exile) target (?:\w+ ){0,4}(?:creature|artifact|enchantment|planeswalker|permanent)\b",
    re.IGNORECASE,
)
_WIPE_RE = re.compile(
    r"(?:destroy all|exile all (?:creatures?|permanents?)"
    r"|all creatures? (?:get|have) -\d+/-\d+"
    r"|each creature (?:gets?|has) -\d+/-\d+"
    r"|deals \d+ damage to each creature)",
    re.IGNORECASE,
)
_HEALTH_THRESHOLDS = {"ramp": 10, "draw": 10, "removal": 8, "wipes": 2}

CARD_ROLE_TAGS = ["Ramp", "Draw", "Removal", "Wipe", "Tutor", "Combo", "Payoff", "Protection"]

_TAG_SET = set(CARD_ROLE_TAGS)


def get_row_tags(row) -> list[str]:
    if not row.tags:
        return []
    try:
        return json.loads(row.tags)
    except (json.JSONDecodeError, TypeError):
        return []


def set_row_tags(row, tags: list[str]) -> None:
    valid = sorted({t for t in tags if t in _TAG_SET})
    row.tags = json.dumps(valid) if valid else None


def get_card_legality(card, format_name: str) -> str | None:
    """Return legality string for the given format, or None if unknown."""
    if not card.legalities or not format_name:
        return None
    try:
        data = json.loads(card.legalities)
    except (json.JSONDecodeError, TypeError):
        return None
    return data.get(format_name.lower())


def suggest_card_roles(card) -> list[str]:
    """Return auto-detected role tags for a card based on oracle text patterns."""
    oracle = (card.oracle_text or "").lower()
    tl = (card.type_line or "").lower()
    if "basic land" in tl or not oracle:
        return []
    is_land = "land" in tl
    is_land_tutor = bool(_RAMP_LAND_RE.search(oracle))
    suggestions = []
    if not is_land and "add {" in oracle:
        suggestions.append("Ramp")
    elif is_land_tutor:
        suggestions.append("Ramp")
    if _DRAW_RE.search(oracle):
        suggestions.append("Draw")
    if _REMOVAL_RE.search(oracle):
        suggestions.append("Removal")
    if _WIPE_RE.search(oracle):
        suggestions.append("Wipe")
    if "search your library for" in oracle and not is_land_tutor:
        suggestions.append("Tutor")
    return suggestions


_TYPE_ORDER = [
    "Creature",
    "Planeswalker",
    "Battle",
    "Instant",
    "Sorcery",
    "Enchantment",
    "Artifact",
    "Land",
]


def compute_deck_analytics(rows: list) -> dict:
    """Compute mana curve, type breakdown, and color pip counts from a list of InventoryRow ORM objects."""
    curve: dict[int, int] = {i: 0 for i in range(7)}
    curve_ramp: dict[int, int] = {i: 0 for i in range(7)}
    curve_spells: dict[int, int] = {i: 0 for i in range(7)}
    types: dict[str, int] = {}
    pips: dict[str, int] = {}
    total_cmc = 0.0
    non_land_copies = 0
    threat_cmc_total = 0.0
    threat_copies = 0

    for row in rows:
        card = row.card
        qty = row.quantity
        tl = (card.type_line or "").lower()
        oracle = (card.oracle_text or "").lower()

        matched = False
        for t in _TYPE_ORDER:
            if t.lower() in tl:
                types[t] = types.get(t, 0) + qty
                matched = True
                break
        if not matched:
            types["Other"] = types.get("Other", 0) + qty

        is_land = "land" in tl
        is_basic = "basic land" in tl

        if not is_land and card.cmc is not None:
            bucket = min(int(card.cmc), 6)
            curve[bucket] += qty
            total_cmc += card.cmc * qty
            non_land_copies += qty

            is_ramp = not is_basic and ("add {" in oracle or bool(_RAMP_LAND_RE.search(oracle)))
            if is_ramp:
                curve_ramp[bucket] += qty
            else:
                curve_spells[bucket] += qty
                threat_cmc_total += card.cmc * qty
                threat_copies += qty

        if card.mana_cost:
            for color in ("W", "U", "B", "R", "G"):
                n = card.mana_cost.count("{" + color + "}") * qty
                if n:
                    pips[color] = pips.get(color, 0) + n

    avg_cmc = round(total_cmc / non_land_copies, 2) if non_land_copies else 0.0
    avg_threat_cmc = round(threat_cmc_total / threat_copies, 1) if threat_copies else 0.0

    total_ramp = sum(curve_ramp.values())
    turns_to_play = max(1, round(avg_threat_cmc) - (1 if total_ramp >= 10 else 0))

    high_cmc_spells = sum(curve_spells[i] for i in range(5, 7))
    dead_hand_pct = round(high_cmc_spells / threat_copies * 100) if threat_copies else 0
    dead_hand_risk = "high" if dead_hand_pct > 45 else ("moderate" if dead_hand_pct > 25 else "low")

    ordered_types = {k: types[k] for k in _TYPE_ORDER if k in types}
    if "Other" in types:
        ordered_types["Other"] = types["Other"]

    return {
        "curve": curve,
        "curve_ramp": curve_ramp,
        "curve_spells": curve_spells,
        "curve_max": max(curve.values()) or 1,
        "types": ordered_types,
        "types_max": max(types.values()) if types else 1,
        "pips": {c: pips[c] for c in ("W", "U", "B", "R", "G") if c in pips},
        "pips_max": max(pips.values()) if pips else 1,
        "avg_cmc": avg_cmc,
        "avg_threat_cmc": avg_threat_cmc,
        "turns_to_play": turns_to_play,
        "dead_hand_risk": dead_hand_risk,
        "dead_hand_pct": dead_hand_pct,
        "total_ramp": total_ramp,
    }


def compute_deck_tokens(rows: list) -> list[dict]:
    """Return deduplicated tokens produceable by cards in this deck."""
    scryfall_ids = [row.card.scryfall_id for row in rows if row.card and row.card.scryfall_id]
    if not scryfall_ids:
        return []
    return fetch_deck_tokens(scryfall_ids)


def compute_consistency(rows: list) -> dict:
    """Compute a 0-100 consistency score from draw density, ramp, tutors, curve smoothness, and role coverage."""
    seen_draw: set[str] = set()
    seen_ramp: set[str] = set()
    seen_tutor: set[str] = set()
    seen_removal: set[str] = set()
    spell_cmcs: list[float] = []

    for row in rows:
        card = row.card
        if not card:
            continue
        name = card.name or ""
        oracle = (card.oracle_text or "").lower()
        tl = (card.type_line or "").lower()
        is_land = "land" in tl
        is_basic = "basic land" in tl

        if not is_land and card.cmc is not None:
            spell_cmcs.extend([card.cmc] * row.quantity)

        if is_basic or not oracle:
            continue

        is_land_tutor = bool(_RAMP_LAND_RE.search(oracle))

        if not is_land and "add {" in oracle and name not in seen_ramp:
            seen_ramp.add(name)
        elif is_land_tutor and name not in seen_ramp:
            seen_ramp.add(name)

        if _DRAW_RE.search(oracle) and name not in seen_draw:
            seen_draw.add(name)

        if "search your library for" in oracle and not is_land_tutor and name not in seen_tutor:
            seen_tutor.add(name)

        if _REMOVAL_RE.search(oracle) and name not in seen_removal:
            seen_removal.add(name)

    draw_n = len(seen_draw)
    ramp_n = len(seen_ramp)
    tutor_n = len(seen_tutor)
    removal_n = len(seen_removal)

    if spell_cmcs:
        mean = sum(spell_cmcs) / len(spell_cmcs)
        variance = sum((c - mean) ** 2 for c in spell_cmcs) / len(spell_cmcs)
        std_dev = round(variance**0.5, 1)
    else:
        std_dev = 0.0

    draw_score = min(25, round(draw_n / 10 * 25))
    ramp_score = min(20, round(ramp_n / 10 * 20))
    tutor_score = min(15, round(tutor_n / 5 * 15))
    smooth_score = 20 if std_dev < 1.5 else (12 if std_dev < 2.5 else 5)
    coverage_raw = min(1.0, ramp_n / 10) + min(1.0, draw_n / 10) + min(1.0, removal_n / 8)
    coverage_score = round(coverage_raw / 3 * 20)
    total = draw_score + ramp_score + tutor_score + smooth_score + coverage_score

    if total >= 80:
        label = "Consistent engine"
    elif total >= 65:
        label = "Stable midrange"
    elif total >= 50:
        label = "Moderate consistency"
    elif total >= 35:
        label = "High variance"
    else:
        label = "Glass cannon"

    if tutor_n >= 5:
        descriptor = "tutor-driven"
    elif draw_n >= 12 and ramp_n >= 10:
        descriptor = "well-oiled"
    elif ramp_n >= 12 and draw_n < 7:
        descriptor = "ramp-heavy"
    elif draw_n >= 10 and ramp_n < 7:
        descriptor = "card-advantage-reliant"
    elif std_dev > 2.5:
        descriptor = "spikey curve"
    else:
        descriptor = None

    tier = "ok" if total >= 65 else ("warn" if total >= 40 else "low")

    return {
        "score": total,
        "label": label,
        "descriptor": descriptor,
        "tier": tier,
        "breakdown": {
            "draw": {"score": draw_score, "max": 25, "count": draw_n},
            "ramp": {"score": ramp_score, "max": 20, "count": ramp_n},
            "tutors": {"score": tutor_score, "max": 15, "count": tutor_n},
            "smoothness": {"score": smooth_score, "max": 20, "std_dev": std_dev},
            "coverage": {"score": coverage_score, "max": 20, "pct": round(coverage_raw / 3 * 100)},
        },
    }


def compute_deck_health(rows: list) -> dict:
    """Compute ramp/draw/removal/wipe density and pip strain from InventoryRow ORM objects."""
    ramp_cards: list[str] = []
    draw_cards: list[str] = []
    removal_cards: list[str] = []
    wipe_cards: list[str] = []
    pip_demand: dict[str, int] = {}
    land_sources: dict[str, int] = {}

    for row in rows:
        card = row.card
        if not card:
            continue
        name = card.name or ""
        oracle = (card.oracle_text or "").lower()
        type_line = (card.type_line or "").lower()
        is_land = "land" in type_line
        is_basic = "basic land" in type_line
        qty = row.quantity

        if not is_land and card.mana_cost:
            for color in ("W", "U", "B", "R", "G"):
                n = card.mana_cost.count("{" + color + "}") * qty
                if n:
                    pip_demand[color] = pip_demand.get(color, 0) + n

        if is_land and card.color_identity is not None:
            for color in ("W", "U", "B", "R", "G"):
                if color in card.color_identity:
                    land_sources[color] = land_sources.get(color, 0) + qty

        if is_basic or not oracle:
            continue

        if not is_land and "add {" in oracle:
            ramp_cards.append(name)
        elif _RAMP_LAND_RE.search(oracle):
            ramp_cards.append(name)

        if _DRAW_RE.search(oracle):
            draw_cards.append(name)

        if _REMOVAL_RE.search(oracle):
            removal_cards.append(name)

        if _WIPE_RE.search(oracle):
            wipe_cards.append(name)

    pip_strain: dict[str, dict] = {}
    for color in ("W", "U", "B", "R", "G"):
        demand = pip_demand.get(color, 0)
        if demand == 0:
            continue
        sources = land_sources.get(color, 0)
        ratio = round(demand / sources, 1) if sources else None
        pip_strain[color] = {
            "demand": demand,
            "sources": sources,
            "ratio": ratio,
            "strained": ratio is None or ratio > 2.5,
        }

    def _metric(cards: list[str], key: str) -> dict:
        unique = sorted(set(cards))
        return {"count": len(unique), "cards": unique, "threshold": _HEALTH_THRESHOLDS[key]}

    return {
        "ramp": _metric(ramp_cards, "ramp"),
        "draw": _metric(draw_cards, "draw"),
        "removal": _metric(removal_cards, "removal"),
        "wipes": _metric(wipe_cards, "wipes"),
        "pip_strain": pip_strain,
    }


def create_deck(
    session: Session,
    user_id: int,
    name: str,
    format_name: str = "",
    notes: str = "",
) -> Deck:
    deck_name = name.strip()

    location = StorageLocation(
        user_id=user_id,
        name=deck_name,
        type="deck",
        parent_id=None,
        sort_order=0,
    )
    session.add(location)
    session.flush()

    deck = Deck(
        user_id=user_id,
        storage_location_id=location.id,
        name=deck_name,
        format=format_name.strip() or None,
        notes=notes.strip() or None,
    )
    session.add(deck)
    session.commit()
    session.refresh(deck)
    return deck


def update_deck(
    session: Session,
    deck_id: int,
    user_id: int,
    name: str,
    format_name: str = "",
    notes: str = "",
) -> Deck:
    deck = get_deck(session, deck_id=deck_id, user_id=user_id)
    if not deck:
        raise ValueError("Deck not found.")

    name = name.strip()
    if not name:
        raise ValueError("Deck name is required.")

    existing = (
        session.query(Deck)
        .filter(Deck.user_id == user_id, Deck.name == name, Deck.id != deck_id)
        .first()
    )
    if existing:
        raise ValueError(f"A deck named '{name}' already exists.")

    deck.name = name
    deck.format = format_name.strip() or None
    deck.notes = notes.strip() or None

    if deck.storage_location_id:
        location = (
            session.query(StorageLocation)
            .filter(
                StorageLocation.id == deck.storage_location_id,
                StorageLocation.user_id == user_id,
            )
            .first()
        )
        if location:
            location.name = name

    session.commit()
    return deck


def list_decks(session: Session, user_id: int) -> list[Deck]:
    decks = (
        session.query(Deck)
        .options(joinedload(Deck.storage_location))
        .filter(Deck.user_id == user_id)
        .order_by(Deck.name.asc())
        .all()
    )

    for deck in decks:
        if not deck.storage_location_id:
            deck.card_count = 0
            continue

        deck.card_count = (
            session.query(func.sum(InventoryRow.quantity))
            .filter(
                InventoryRow.user_id == user_id,
                InventoryRow.storage_location_id == deck.storage_location_id,
            )
            .scalar()
            or 0
        )

        commander_rows = (
            session.query(InventoryRow)
            .join(Card)
            .filter(
                InventoryRow.user_id == user_id,
                InventoryRow.storage_location_id == deck.storage_location_id,
                InventoryRow.role == "commander",
            )
            .all()
        )
        seen: set[str] = set()
        for row in commander_rows:
            for letter in (row.card.color_identity or "").split():
                seen.add(letter)
        deck.color_identity = " ".join(p for p in ["W", "U", "B", "R", "G"] if p in seen)

    return decks


def get_deck(session: Session, deck_id: int, user_id: int) -> Deck | None:
    return (
        session.query(Deck)
        .options(joinedload(Deck.storage_location))
        .filter(
            Deck.id == deck_id,
            Deck.user_id == user_id,
        )
        .first()
    )


def pull_card_to_deck(
    session: Session,
    user_id: int,
    deck_id: int,
    inventory_row_id: int,
    quantity: int,
) -> bool:
    if quantity < 1:
        return False

    deck = (
        session.query(Deck)
        .filter(
            Deck.id == deck_id,
            Deck.user_id == user_id,
        )
        .first()
    )

    row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.id == inventory_row_id,
            InventoryRow.user_id == user_id,
        )
        .first()
    )

    if not row or not deck or not deck.storage_location_id or row.quantity < quantity:
        return False

    existing_deck_row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.card_id == row.card_id,
            InventoryRow.finish == row.finish,
            InventoryRow.storage_location_id == deck.storage_location_id,
            InventoryRow.is_pending.is_(False),
        )
        .first()
    )

    if existing_deck_row:
        existing_deck_row.quantity += quantity
        existing_deck_row.updated_at = datetime.utcnow()
    else:
        existing_deck_row = InventoryRow(
            user_id=user_id,
            card_id=row.card_id,
            storage_location_id=deck.storage_location_id,
            finish=row.finish,
            quantity=quantity,
            drawer=None,
            slot=None,
            is_pending=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(existing_deck_row)
        session.flush()

    row.quantity -= quantity
    row.updated_at = datetime.utcnow()

    if row.quantity <= 0:
        session.delete(row)

    log_transaction(
        session=session,
        user_id=user_id,
        event_type="pull_to_deck",
        card_id=existing_deck_row.card_id,
        finish=existing_deck_row.finish,
        quantity_delta=-quantity,
        source_location="collection",
        destination_location=f"deck:{deck.name}",
        inventory_row_id=existing_deck_row.id,
        note=f"Pulled into deck {deck.name}",
    )

    session.commit()
    return True


def return_card_from_deck(
    session: Session,
    user_id: int,
    deck_row_id: int,
    drawer: str = "",
    slot: str = "",
) -> bool:
    deck_row = (
        session.query(InventoryRow)
        .options(joinedload(InventoryRow.card))
        .join(
            Deck,
            Deck.storage_location_id == InventoryRow.storage_location_id,
        )
        .filter(
            Deck.user_id == user_id,
            InventoryRow.id == deck_row_id,
            InventoryRow.user_id == user_id,
        )
        .first()
    )

    if not deck_row:
        return False

    deck = (
        session.query(Deck)
        .filter(
            Deck.user_id == user_id,
            Deck.storage_location_id == deck_row.storage_location_id,
        )
        .first()
    )

    if not deck:
        return False

    normalized_drawer = drawer.strip() or None
    normalized_slot = slot.strip() or None

    existing_row = (
        session.query(InventoryRow)
        .filter(
            InventoryRow.user_id == user_id,
            InventoryRow.card_id == deck_row.card_id,
            InventoryRow.finish == deck_row.finish,
            InventoryRow.drawer == normalized_drawer,
            InventoryRow.slot == normalized_slot,
            InventoryRow.is_pending.is_(True),
        )
        .first()
    )

    if existing_row:
        existing_row.quantity += deck_row.quantity
        existing_row.storage_location_id = None
        existing_row.is_pending = True
        existing_row.updated_at = datetime.utcnow()
    else:
        existing_row = InventoryRow(
            user_id=user_id,
            card_id=deck_row.card_id,
            finish=deck_row.finish,
            quantity=deck_row.quantity,
            drawer=normalized_drawer,
            slot=normalized_slot,
            storage_location_id=None,
            is_pending=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(existing_row)
        session.flush()

    log_transaction(
        session=session,
        user_id=user_id,
        event_type="return_from_deck",
        card_id=deck_row.card_id,
        finish=deck_row.finish,
        quantity_delta=deck_row.quantity,
        source_location=f"deck:{deck.name}",
        destination_location="collection",
        inventory_row_id=existing_row.id,
        note=f"Returned from deck {deck.name}",
    )

    session.delete(deck_row)
    session.commit()
    return True


def delete_deck(session: Session, deck_id: int, user_id: int) -> bool:
    deck = get_deck(session, deck_id=deck_id, user_id=user_id)
    if not deck:
        return False

    if deck.storage_location_id:
        # Delete all inventory rows in this deck
        deck_rows = (
            session.query(InventoryRow)
            .filter(
                InventoryRow.user_id == user_id,
                InventoryRow.storage_location_id == deck.storage_location_id,
            )
            .all()
        )

        for row in deck_rows:
            session.delete(row)

        # Delete the storage location itself
        location = (
            session.query(StorageLocation)
            .filter(
                StorageLocation.id == deck.storage_location_id,
                StorageLocation.user_id == user_id,
            )
            .first()
        )

        if location:
            session.delete(location)

    # Delete the deck
    session.delete(deck)
    session.commit()
    return True
