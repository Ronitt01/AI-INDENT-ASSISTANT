"""Lexicon loading and term matching.

The lexicon holds ~7,000 surface forms across ten Indian languages and English.
For every concept it carries three classes of term, because callers speak
code-switched and the STT transliterates English logistics jargon into the local
script:

* the native word (Hindi ``लोहा`` for iron)
* the English loanword written in that script (``स्टील``, ``مٹیریل``)
* the ASCII romanisation a caller might type ("steel", "tan")

The middle class is usually the highest-value one — Indian logistics vocabulary
is overwhelmingly English loanwords.

Matching is one compiled alternation per group rather than one regex per term.
Per-term regexes meant ~7,000 compiled patterns and ~7,000 scans per utterance
(~313ms), which cannot keep pace with live speech; the alternation form runs in
well under a millisecond.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

LEXICON_PATH = Path(__file__).resolve().parents[1] / "data" / "lexicon.json"

with LEXICON_PATH.open("r", encoding="utf-8") as fh:
    LEXICON: dict[str, Any] = json.load(fh)


def _boundary(pattern: str) -> str:
    r"""A Unicode-aware word boundary.

    ``\b`` is ASCII-oriented and happily matches inside a Devanagari or Arabic
    word, so these lookarounds stand in for it: no letter or digit either side.
    """
    return rf"(?<![^\W\d_]|\d){pattern}(?![^\W\d_]|\d)"


@dataclass(frozen=True)
class Hit:
    """One matched term, and where in the text it was found."""

    canonical: str
    index: int
    length: int
    term: str


@lru_cache(maxsize=None)
def _matcher(group_key: str) -> tuple[re.Pattern[str] | None, tuple[tuple[str, str], ...]]:
    """Compile one alternation for a lexicon group.

    Terms are ordered longest-first so Python's leftmost-then-ordered
    alternation yields the most specific match at each position — "open body
    truck" wins over a bare "truck". A single global scan cannot return
    overlapping matches, so no de-duplication pass is needed afterwards.
    """
    entries = LEXICON.get(group_key) or []
    lookup: dict[str, str] = {}
    for entry in entries:
        canonical = entry.get("canonical")
        for term in entry.get("terms", []):
            if term and term not in lookup:
                lookup[term] = canonical
    if not lookup:
        return None, ()
    body = "|".join(re.escape(t) for t in sorted(lookup, key=len, reverse=True))
    return re.compile(_boundary(f"(?:{body})"), re.IGNORECASE | re.UNICODE), tuple(lookup.items())


def find_terms(haystack: str, group_key: str) -> list[Hit]:
    """Every occurrence of any term in a lexicon group, in document order."""
    pattern, pairs = _matcher(group_key)
    if pattern is None:
        return []
    lookup = dict(pairs)
    hits: list[Hit] = []
    for m in pattern.finditer(haystack):
        canonical = lookup.get(m.group(0).lower())
        if canonical is not None:
            hits.append(Hit(canonical, m.start(), len(m.group(0)), m.group(0).lower()))
    return hits


def alternation(group_key: str) -> str:
    """Longest-first alternation body for a group, for embedding in a larger pattern."""
    entries = LEXICON.get(group_key) or []
    terms = {t for e in entries for t in e.get("terms", []) if t}
    return "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))


def canonical_for(group_key: str, term: str, normalizer) -> str | None:
    """Canonical value for a raw surface form, or None if unrecognised."""
    target = normalizer(term)
    for entry in LEXICON.get(group_key, []):
        if any(normalizer(t) == target for t in entry.get("terms", [])):
            return entry["canonical"]
    return None
