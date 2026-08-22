"""Parsing the two value types that are not simple vocabulary lookups.

Dates and quantities are numeric-plus-unit constructions, so they need real
patterns rather than a term list — and both arrive damaged by the way STT
fragments speech.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .lexicon import LEXICON, _boundary, alternation, find_terms
from .normalize import normalize


@lru_cache(maxsize=None)
def _quantity_re() -> re.Pattern[str]:
    return re.compile(
        rf"(\d+(?:[.,]\d+)?)\s*({alternation('units')})(?![^\W\d_])",
        re.IGNORECASE | re.UNICODE,
    )


@lru_cache(maxsize=None)
def _day_month_re() -> re.Pattern[str]:
    """Day-then-month, with separators optional *and* repeatable.

    STT splits a date across chunks and each chunk keeps its own punctuation, so
    "21/." followed by "ستمبر۔" joins as "21/. ستمبر" — two separator characters
    between the day and the month.
    """
    return re.compile(
        rf"(?<![^\W\d_]|\d)(\d{{1,2}})\s*(?:st|nd|rd|th)?[\s/\-.,]*(?:of\s+)?"
        rf"({alternation('months')})(?![^\W\d_])\s*,?\s*(\d{{4}})?",
        re.IGNORECASE | re.UNICODE,
    )


@lru_cache(maxsize=None)
def _month_day_re() -> re.Pattern[str]:
    return re.compile(
        rf"(?<![^\W\d_]|\d)({alternation('months')})(?![^\W\d_])\s*[,\-]?\s*(\d{{1,2}})"
        rf"(?![^\W\d_]|\d)\s*,?\s*(\d{{4}})?",
        re.IGNORECASE | re.UNICODE,
    )


_NUMERIC_DATE_RE = re.compile(
    r"(?<![^\W\d_]|\d)(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{2,4}))?(?![^\W\d_]|\d)"
)


@lru_cache(maxsize=1)
def _month_canonicals() -> dict[str, str]:
    return {
        normalize(term): entry["canonical"]
        for entry in LEXICON.get("months", [])
        for term in entry.get("terms", [])
    }


@lru_cache(maxsize=1)
def _unit_canonicals() -> dict[str, str]:
    return {
        normalize(term): entry["canonical"]
        for entry in LEXICON.get("units", [])
        for term in entry.get("terms", [])
    }


def month_canonical(raw: str) -> str:
    return _month_canonicals().get(normalize(raw), raw)


def unit_canonical(raw: str) -> str | None:
    return _unit_canonicals().get(normalize(raw))


def collect_quantities(text: str) -> list[tuple[int, str, str]]:
    """``(index, value, raw)`` for each quantity mentioned."""
    out: list[tuple[int, str, str]] = []
    for m in _quantity_re().finditer(text):
        unit = unit_canonical(m.group(2)) or m.group(2)
        out.append((m.start(), f"{m.group(1).replace(',', '')} {unit}", m.group(0)))
    return out


def collect_dates(text: str) -> list[tuple[int, str, str]]:
    """``(index, value, raw)`` for each date, de-duplicated by position."""
    hits: list[tuple[int, str, str]] = []

    for m in _day_month_re().finditer(text):
        year = f" {m.group(3)}" if m.group(3) else ""
        hits.append((m.start(), f"{int(m.group(1))} {month_canonical(m.group(2))}{year}", m.group(0)))

    for m in _month_day_re().finditer(text):
        year = f" {m.group(3)}" if m.group(3) else ""
        hits.append((m.start(), f"{int(m.group(2))} {month_canonical(m.group(1))}{year}", m.group(0)))

    for m in _NUMERIC_DATE_RE.finditer(text):
        day, month = int(m.group(1)), int(m.group(2))
        if day > 31 or not 1 <= month <= 12:
            continue
        tail = f"/{m.group(3)}" if m.group(3) else ""
        hits.append((m.start(), f"{day}/{month}{tail}", m.group(0)))

    for hit in find_terms(text, "relativeDates"):
        hits.append((hit.index, hit.canonical, hit.term))

    hits.sort(key=lambda h: h[0])
    kept: list[tuple[int, str, str]] = []
    for h in hits:
        if not any(abs(k[0] - h[0]) < 3 for k in kept):
            kept.append(h)
    return kept
