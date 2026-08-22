"""Markers: the words that say which field a value belongs to.

Two kinds, and conflating them is the bug this module exists to prevent:

* **Field labels** — "pickup location", "डिलीवरी डेट". These precede their value
  in every language here, including transliterated Hinglish.
* **Route markers** — "from"/"to" and their Indic equivalents. English is
  prepositional ("FROM Delhi"); every Indian language here is *postpositional*
  (``दिल्ली से`` is "Delhi FROM"), including romanised forms ("Delhi se"). The
  binding direction is recorded per marker at lexicon build time. Treating a
  postposition as a preposition silently swaps origin and destination.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence

from .lexicon import LEXICON, _boundary

#: How far back a label may sit from the value it labels.
MARKER_WINDOW = 90
#: A postposition sits immediately after its noun, so this stays tight.
POSTPOSITION_WINDOW = 5


@dataclass(frozen=True)
class Marker:
    index: int
    length: int
    #: "pre" — the label precedes its value. "post" — a postposition follows it.
    bind: str


def _terms_at(path: str) -> tuple[str, ...]:
    node: Any = LEXICON
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return tuple(t for t in node if t) if isinstance(node, list) else ()


@lru_cache(maxsize=None)
def _pattern_at(path: str) -> re.Pattern[str] | None:
    terms = _terms_at(path)
    if not terms:
        return None
    body = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(_boundary(f"(?:{body})"), re.IGNORECASE | re.UNICODE)


def find_markers(haystack: str, path: str, bind: str = "pre") -> list[Marker]:
    pattern = _pattern_at(path)
    if pattern is None:
        return []
    return [Marker(m.start(), len(m.group(0)), bind) for m in pattern.finditer(haystack)]


def field_markers(haystack: str, field: str) -> list[Marker]:
    """Labels for one indent field, e.g. ``pickup`` or ``deliveryDate``."""
    return find_markers(haystack, f"fieldMarkers.{field}")


def route_markers(haystack: str, direction: str) -> list[Marker]:
    """Origin ("from") or destination ("to") markers, each carrying its binding."""
    out: list[Marker] = []
    for bind in ("pre", "post"):
        out.extend(find_markers(haystack, f"routeMarkers.{direction}.{bind}", bind))
    return out


@lru_cache(maxsize=1)
def marker_words() -> frozenset[str]:
    """Every individual word used in any marker.

    A guess that runs into one of these has left its value and wandered into the
    next clause — "delivery location ... pickup date" must not be guessed as a
    place called "Date".
    """
    words: set[str] = set()
    for arr in (LEXICON.get("fieldMarkers") or {}).values():
        for marker in arr or []:
            words.update(marker.split(" "))
    for direction in ("from", "to"):
        spec = (LEXICON.get("routeMarkers") or {}).get(direction) or {}
        for bind in ("pre", "post"):
            for marker in spec.get(bind, []) or []:
                words.update(marker.split(" "))
    return frozenset(words)


def role_for(index: int, length: int, a: Sequence[Marker], b: Sequence[Marker]) -> str | None:
    """Which of two roles a value at this position belongs to, by nearest marker."""
    best_dist = 10**9
    best_len = -1
    role: str | None = None
    for markers, name in ((a, "a"), (b, "b")):
        for m in markers:
            if m.bind == "post":
                dist = m.index - (index + length)
                limit = POSTPOSITION_WINDOW
            else:
                dist = index - (m.index + m.length)
                limit = MARKER_WINDOW
            if dist < 0 or dist > limit:
                continue
            # Equal distance means the markers overlap — a generic cue sitting
            # inside a specific one ("date" within "delivery date"). The longer,
            # more specific marker must win, or every delivery date files as a
            # pickup date.
            if dist < best_dist or (dist == best_dist and m.length > best_len):
                best_dist, best_len, role = dist, m.length, name
    return role


def split_by_role(
    items: Sequence[tuple[int, int, Any]],
    a: Sequence[Marker],
    b: Sequence[Marker],
) -> tuple[list[Any], list[Any]]:
    """Assign values to two roles by marker proximity, falling back to order."""
    ra: list[Any] = []
    rb: list[Any] = []
    unassigned: list[Any] = []
    for index, length, payload in items:
        role = role_for(index, length, a, b)
        if role == "a":
            ra.append(payload)
        elif role == "b":
            rb.append(payload)
        else:
            unassigned.append(payload)

    # Nothing was labelled: the conventional order is origin first, destination
    # second ("Pune to Nagpur", "21 Sep ... 25 Sep").
    if not ra and not rb and len(unassigned) >= 2:
        return [unassigned[0]], [unassigned[-1]]
    if not ra and unassigned:
        return [unassigned[0]], rb
    if not rb and unassigned:
        tail = [u for u in unassigned if u not in ra]
        if tail:
            return ra, [tail[-1]]
    return ra, rb
