"""
Physical sorting logic for the 6-drawer storage unit.

Drawer assignment rules
-----------------------
Drawer 1  : price >= $5.00 (value cards), ordered by set code then collector number
Drawer 2  : set code begins A–D, ordered by set code then collector number
Drawer 3  : set code begins E–L, ordered by set code then collector number
Drawer 4  : set code begins M–R, ordered by set code then collector number
Drawer 5  : set code begins S–Z, ordered by set code then collector number
Drawer 6  : set code begins with a non-letter (e.g. "2x2"), ordered by set code then collector number
"""
from __future__ import annotations

import re

VALUE_THRESHOLD = 5.00

# Alphabetical bin boundaries keyed on the first character of the set code:
# (start_char_inclusive, end_char_inclusive, drawer)
_SET_CODE_BINS: list[tuple[str, str, int]] = [
    ("a", "d", 2),
    ("e", "l", 3),
    ("m", "r", 4),
    ("s", "z", 5),
]

# Collector numbers often contain a leading integer followed by optional
# letters (e.g. "42", "42a", "★1").  Splitting on the numeric prefix lets us
# sort them naturally (1, 2, 10) instead of lexicographically (1, 10, 2).
_COLLECTOR_NUM_RE = re.compile(r"^(\d+)(.*)")


def assign_drawer(set_code: str, price: float | None) -> int:
    """
    Return the drawer number (1-6) for a card given its set code and USD price.

    Parameters
    ----------
    set_code : Scryfall set code (e.g. "lea", "2x2", "neo").
    price    : USD price for the relevant finish. Pass None to treat as 0.00.

    Returns
    -------
    int : Drawer number 1-6.
    """
    effective_price = price if price is not None else 0.0

    if effective_price >= VALUE_THRESHOLD:
        return 1

    first_char = set_code.strip().lower()[:1] if set_code.strip() else ""

    if not first_char or not first_char.isalpha():
        return 6

    for start, end, drawer in _SET_CODE_BINS:
        if start <= first_char <= end:
            return drawer

    return 6


def _collector_number_sort_key(collector_number: str) -> tuple[int, str]:
    """
    Parse a collector number into (integer_part, suffix) for natural sorting.

    "1"   -> (1,   "")
    "10"  -> (10,  "")
    "10a" -> (10,  "a")
    "★1"  -> (0,   "★1")   # non-numeric prefix sorts before numeric
    """
    stripped = collector_number.strip()
    m = _COLLECTOR_NUM_RE.match(stripped)
    if m:
        return int(m.group(1)), m.group(2).lower()
    return (0, stripped.lower())


def sort_key_for_card(set_code: str, collector_number: str) -> tuple[str, int, str]:
    """
    Return a sort key tuple (set_code_lower, collector_int, collector_suffix)
    used to determine physical position within a drawer.

    Cards are ordered first by set code alphabetically, then by collector
    number numerically.
    """
    num_part, suffix = _collector_number_sort_key(collector_number)
    return (set_code.strip().lower(), num_part, suffix)
