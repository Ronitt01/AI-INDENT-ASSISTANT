"""How much we trust a captured value, and therefore who may overwrite whom.

Several sources disagree about the same field during a call — a heuristic guess,
a lexicon match, the model's own extraction, the caller confirming it, an
operator typing over it. Ranking them means the arbitration rule lives in one
place instead of being re-decided at every call site.
"""

from __future__ import annotations

from enum import IntEnum


class Confidence(IntEnum):
    """Higher wins. A value may only be replaced by one of equal or greater rank."""

    #: A label was heard but the value itself was not recognised.
    GUESSED = 1
    #: Matched the lexicon in the caller's own speech.
    HEARD = 2
    #: The model called ``upsert_indent`` with this value.
    EXTRACTED = 3
    #: The caller explicitly confirmed this value back.
    CONFIRMED = 4
    #: An operator typed it. Nothing automatic may overwrite this.
    EDITED = 5


#: Human-readable labels, shared with the operator console.
LABELS: dict[int, str] = {
    Confidence.GUESSED: "guessed",
    Confidence.HEARD: "heard",
    Confidence.EXTRACTED: "extracted",
    Confidence.CONFIRMED: "confirmed",
    Confidence.EDITED: "edited",
}
