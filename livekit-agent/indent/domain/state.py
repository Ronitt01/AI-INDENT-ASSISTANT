"""The indent itself: captured values, their provenance, and the write rule.

``IndentState`` is deliberately not a plain dict. Every write goes through
:meth:`IndentState.upsert`, so the confidence rule and the history trail cannot
be bypassed by an accidental direct assignment somewhere else in the codebase.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .confidence import Confidence
from .fields import FIELD_BY_KEY, FIELD_KEYS, FIELDS, FieldDef


@dataclass
class SlotHistory:
    """A value this field used to hold."""

    value: str
    confidence: int
    source: str
    at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Slot:
    """One captured field plus everything needed to explain it later.

    Provenance is not decoration. When a value is wrong the operator's first
    question is "where did that come from?", and without the utterance and the
    matched term there is nothing to answer it with.
    """

    value: str
    confidence: int
    source: str                      # llm | speech | operator | validation
    term: str | None = None          # the literal text that matched
    utterance: str | None = None     # what was being said at the time
    at: float = field(default_factory=time.time)
    history: list[SlotHistory] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": int(self.confidence),
            "source": self.source,
            "term": self.term,
            "utterance": self.utterance,
            "at": self.at,
            "history": [h.to_dict() for h in self.history],
            "warnings": list(self.warnings),
        }


class IndentState:
    """The live indent for one call."""

    def __init__(self) -> None:
        self.slots: dict[str, Slot] = {}
        self.confirmed: bool = False

    # -- reads -------------------------------------------------------------

    def value(self, key: str) -> str | None:
        slot = self.slots.get(key)
        return slot.value if slot else None

    def missing(self) -> list[FieldDef]:
        return [f for f in FIELDS if f.key not in self.slots]

    def is_complete(self) -> bool:
        return not self.missing()

    def next_prompt(self) -> str | None:
        missing = self.missing()
        return missing[0].prompt if missing else None

    # -- writes ------------------------------------------------------------

    def upsert(
        self,
        key: str,
        value: str,
        confidence: int,
        source: str,
        *,
        term: str | None = None,
        utterance: str | None = None,
        warnings: Iterable[str] | None = None,
    ) -> bool:
        """Set a field. Returns True if the state actually changed.

        Rejects a write less confident than what is already stored, so a late
        low-confidence guess cannot clobber a confirmed value.
        """
        if key not in FIELD_BY_KEY:
            raise KeyError(f"unknown indent field: {key}")
        value = (value or "").strip()
        if not value:
            return False

        prev = self.slots.get(key)
        if prev is not None:
            if confidence < prev.confidence:
                return False
            if prev.value == value and confidence == prev.confidence:
                return False

        self.slots[key] = Slot(
            value=value,
            confidence=int(confidence),
            source=source,
            term=term,
            utterance=utterance,
            history=self._history_after(prev, confidence),
            warnings=list(warnings or []),
        )
        # Any change invalidates a prior confirmation: the caller confirmed
        # something different from what we now hold.
        if prev is not None and prev.value != value:
            self.confirmed = False
        return True

    @staticmethod
    def _history_after(prev: Slot | None, confidence: int) -> list[SlotHistory]:
        """Guess-to-guess churn is refinement as more of the sentence arrives,
        not correction — recording it would bury the change that matters."""
        if prev is None:
            return []
        history = list(prev.history)
        if prev.confidence >= Confidence.HEARD or confidence > prev.confidence:
            history.append(
                SlotHistory(prev.value, int(prev.confidence), prev.source, prev.at)
            )
        return history

    def clear(self, key: str) -> bool:
        return self.slots.pop(key, None) is not None

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields": {k: s.to_dict() for k, s in self.slots.items()},
            "complete": self.is_complete(),
            "confirmed": self.confirmed,
            "missing": [f.key for f in self.missing()],
        }

    def to_plain(self) -> dict[str, str | None]:
        """Just the values — what a downstream system actually wants."""
        return {k: self.value(k) for k in FIELD_KEYS}
