"""Pulling all eight fields out of a block of transcript text.

This is the orchestration layer over :mod:`lexicon`, :mod:`markers` and
:mod:`values`. In the current stack it is the *second* opinion — Gemini's
``upsert_indent`` tool call is primary — so everything here lands at HEARD or
GUESSED, below the model's EXTRACTED, and can fill a gap but never override a
considered extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..domain.confidence import Confidence
from .lexicon import LEXICON, find_terms
from .markers import (
    Marker,
    field_markers,
    marker_words,
    route_markers,
    split_by_role,
)
from .normalize import normalize, strip_questions
from .values import collect_dates, collect_quantities

_STOP_TOKENS = frozenset(LEXICON.get("stopTokens", []))


@dataclass(frozen=True)
class Detected:
    value: str
    confidence: int
    term: str


def _title(s: str) -> str:
    """Title-case Latin words, leave other scripts untouched."""
    return " ".join(
        w[:1].upper() + w[1:] if re.search(r"[a-z]", w, re.I) else w
        for w in str(s).split()
    )


def _guess_after(text: str, markers: list[Marker]) -> tuple[int, str] | None:
    """Last-ditch place-name guess: the token(s) right after a field label.

    Only ever called for pickup/delivery labels, never for a bare preposition —
    "from" is everywhere in ordinary speech, and "I'm Rhea from AB Logistics"
    would otherwise book a pickup at "Ab Logistics". A blank field beats a
    confidently wrong one.
    """
    if not markers:
        return None
    marker = markers[-1]
    start = marker.index + marker.length
    tail = text[start:start + 60]

    picked: list[str] = []
    for token in (t for t in re.split(r"[\s,.]+", tail) if t):
        # Filler first: copulas like "hai"/"है" sit *inside* marker phrases
        # ("डिलीवरी लोकेशन है"), so testing marker words first would abort on the
        # very word that separates a label from its value.
        if token in _STOP_TOKENS:
            if picked:
                break
            continue
        if token in marker_words():
            break
        if token.isdigit():
            break
        picked.append(token)
        if len(picked) >= 2:
            break

    return (marker.index, " ".join(picked)) if picked else None


def detect_fields(raw_text: str, *, agent: bool = False) -> dict[str, Detected]:
    """Every field findable in ``raw_text``.

    ``agent=True`` strips interrogative sentences first, so an agent offering
    options cannot fill the field it is asking about.
    """
    text = normalize(strip_questions(raw_text) if agent else raw_text)
    if not text:
        return {}

    base = Confidence.HEARD
    out: dict[str, Detected] = {}

    def put(key: str, value: str, confidence: int, term: str | None = None) -> None:
        clean = _title(str(value).strip())
        if not clean:
            return
        prev = out.get(key)
        if prev is None or confidence >= prev.confidence:
            out[key] = Detected(clean, int(confidence), term or clean)

    pickup_marks = field_markers(text, "pickup")
    delivery_marks = field_markers(text, "delivery")
    from_marks = route_markers(text, "from")
    to_marks = route_markers(text, "to")

    # --- locations ---
    # Recognised cities first, then guess for whichever end is still empty: one
    # known city must not suppress the guess for the other, or
    # "Bengaluru to <somewhere unlisted>" silently drops the destination.
    pickup_value: str | None = None
    delivery_value: str | None = None

    city_hits = find_terms(text, "cities")
    if city_hits:
        a, b = split_by_role(
            [(h.index, h.length, h) for h in city_hits],
            pickup_marks + from_marks,
            delivery_marks + to_marks,
        )
        if a:
            put("pickupLocation", a[-1].canonical, base, a[-1].term)
            pickup_value = a[-1].canonical
        if b and b[-1].canonical != pickup_value:
            put("deliveryLocation", b[-1].canonical, base, b[-1].term)
            delivery_value = b[-1].canonical

    if pickup_value is None:
        guess = _guess_after(text, pickup_marks)
        if guess and guess[1] != delivery_value:
            put("pickupLocation", guess[1], Confidence.GUESSED, guess[1])
            pickup_value = guess[1]
    if delivery_value is None:
        guess = _guess_after(text, delivery_marks)
        if guess and guess[1] != pickup_value:
            put("deliveryLocation", guess[1], Confidence.GUESSED, guess[1])

    # --- closed vocabularies: last mention wins, because callers correct themselves ---
    for group, key in (
        ("materials", "material"),
        ("vehicles", "vehicleType"),
        ("procurement", "procurementType"),
    ):
        hits = find_terms(text, group)
        if hits:
            put(key, hits[-1].canonical, base, hits[-1].term)

    # --- quantity ---
    quantities = collect_quantities(text)
    if quantities:
        _, value, raw = quantities[-1]
        put("quantity", value, base, raw)

    # --- dates ---
    dates = collect_dates(text)
    if dates:
        a, b = split_by_role(
            [(idx, len(raw), (value, raw)) for idx, value, raw in dates],
            field_markers(text, "pickupDate"),
            field_markers(text, "deliveryDate"),
        )
        if a:
            put("pickupDate", a[-1][0], base, a[-1][1])
        if b and (not a or b[-1][0] != a[-1][0]):
            put("deliveryDate", b[-1][0], base, b[-1][1])

    return out
