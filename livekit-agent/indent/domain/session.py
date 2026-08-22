"""Ties the pieces together for one call.

Deliberately free of LiveKit imports: everything here is pure state and can be
unit-tested without a room, a socket, or an API key. ``agent.py`` is the only
place that knows about LiveKit.

Two sources feed the same indent and they are not equal:

* the **LLM tool call** is primary - the model has understood the whole
  conversation and resolved it to a value;
* the **lexicon** is the second opinion - it fills gaps when a tool call is
  missing or malformed, and it validates what the model produced.

The confidence ladder in :mod:`schema` arbitrates between them, so neither path
needs to know about the other.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from ..extraction import TranscriptWindow, detect_fields, detect_script
from ..validation import Issue, blocking, resolve_date, resolve_quantity, validate_indent
from .confidence import Confidence
from .fields import FIELD_BY_KEY, FIELD_KEYS
from .state import IndentState


@dataclass
class TurnMetric:
    """Timing for one exchange.

    ``response_ms`` is measured to the moment the agent's audio *starts*, never
    to its final transcript - that arrives only after the sentence has finished
    playing and would fold the whole speaking duration into the number. Agent
    speaking time is tracked separately because it is a duration, not a latency.
    """

    response_ms: int | None = None
    talk_ms: int | None = None
    barge_in: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"responseMs": self.response_ms, "talkMs": self.talk_ms, "bargeIn": self.barge_in}


@dataclass
class Utterance:
    role: str            # user | agent | system
    text: str
    at: float
    language: dict[str, str] | None = None
    barge_in: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "text": self.text,
            "at": self.at,
            "language": self.language,
            "bargeIn": self.barge_in,
        }


class IndentSession:
    """Live indent capture for a single call."""

    def __init__(
        self,
        *,
        call_id: str,
        reference_date: date | None = None,
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.call_id = call_id
        self.state = IndentState()
        self.reference_date = reference_date
        self.on_change = on_change

        self.transcript: list[Utterance] = []
        self.metrics: list[TurnMetric] = []
        self.languages: dict[str, int] = {}
        self.total_talk_ms: int = 0
        self.started_at: float = time.time()

        self._user_window = TranscriptWindow()
        self._agent_window = TranscriptWindow()
        self._turn_open: dict[str, Any] | None = None
        self._agent_speaking = False
        self._agent_speech_started: float | None = None

    # -- transcripts -------------------------------------------------------

    def add_user_speech(self, text: str) -> bool:
        """Record what the caller said and run the lexicon over the rolling window.

        Values land at HEARD/GUESSED, below the LLM's EXTRACTED, so this can fill
        a gap but never override a considered extraction.
        """
        barge_in = self._agent_speaking
        language = detect_script(text)
        if language:
            self.languages[language["label"]] = self.languages.get(language["label"], 0) + 1
        self.transcript.append(
            Utterance("user", text, time.time(), language, barge_in)
        )
        self._open_turn(barge_in=barge_in)

        joined = self._user_window.push(text)
        changed = self._apply_detected(detect_fields(joined), source="speech", utterance=text)
        self._emit()
        return changed

    def add_agent_speech(self, text: str) -> bool:
        """The agent's own words. Questions are stripped inside ``detect_fields``
        so listing options ("truck, trailer, or tanker?") cannot fill a field."""
        self.transcript.append(Utterance("agent", text, time.time(), detect_script(text)))
        joined = self._agent_window.push(text)
        changed = self._apply_detected(
            detect_fields(joined, agent=True), source="speech", utterance=text
        )
        self._emit()
        return changed

    def add_system_note(self, text: str) -> None:
        self.transcript.append(Utterance("system", text, time.time()))
        self._emit()

    def _apply_detected(self, detected, *, source: str, utterance: str) -> bool:
        changed = False
        for key, hit in detected.items():
            value, warnings = self._resolve(key, hit.value)
            if self.state.upsert(
                key, value, hit.confidence, source,
                term=hit.term, utterance=utterance, warnings=warnings,
            ):
                changed = True
        return changed

    # -- LLM tool calls ----------------------------------------------------

    def apply_extraction(
        self,
        key: str,
        value: str,
        *,
        confirmed: bool = False,
        utterance: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Apply one ``upsert_indent`` call from the model.

        Returns ``(changed, warnings)``. Warnings are handed back so the agent can
        say them out loud - "I've assumed 2027, is that right?" - rather than
        burying an assumption in a log nobody reads.
        """
        if key not in FIELD_BY_KEY:
            return False, [f"unknown field '{key}'"]

        resolved, warnings = self._resolve(key, value)
        confidence = Confidence.CONFIRMED if confirmed else Confidence.EXTRACTED
        changed = self.state.upsert(
            key, resolved, confidence, "llm",
            term=value, utterance=utterance, warnings=warnings,
        )
        if changed:
            self._emit()
        return changed, warnings

    def apply_operator_edit(self, key: str, value: str) -> bool:
        """A hand correction. Sits at the top of the ladder - nothing automatic
        may overwrite it for the rest of the call."""
        if key not in FIELD_BY_KEY:
            return False
        if not value.strip():
            changed = self.state.clear(key)
        else:
            resolved, warnings = self._resolve(key, value)
            changed = self.state.upsert(
                key, resolved, Confidence.EDITED, "operator",
                term=value, utterance="typed by operator", warnings=warnings,
            )
        if changed:
            self._emit()
        return changed

    def _resolve(self, key: str, value: str) -> tuple[str, list[str]]:
        """Normalise a single field as it arrives, keeping the raw value if it
        cannot be resolved - a value we cannot parse is still worth showing."""
        if key in ("pickupDate", "deliveryDate"):
            res = resolve_date(value, reference=self.reference_date)
            return (res.value, res.warnings) if res.ok else (value, res.warnings)
        if key == "quantity":
            res = resolve_quantity(value)
            return (res.value, res.warnings) if res.ok else (value, res.warnings)
        return value, []

    # -- confirmation ------------------------------------------------------

    def issues(self) -> list[Issue]:
        return validate_indent(self.state.to_plain(), reference=self.reference_date)

    def can_confirm(self) -> tuple[bool, list[str]]:
        if not self.state.is_complete():
            missing = [FIELD_BY_KEY[k].label for k in self.state.to_dict()["missing"]]
            return False, [f"still missing: {', '.join(missing)}"]
        errors = blocking(self.issues())
        if errors:
            return False, [f"{i.field}: {i.message}" for i in errors]
        return True, []

    def confirm(self) -> tuple[bool, list[str]]:
        ok, reasons = self.can_confirm()
        if ok:
            self.state.confirmed = True
            self._emit()
        return ok, reasons

    # -- metrics -----------------------------------------------------------

    def _open_turn(self, *, barge_in: bool) -> None:
        self._turn_open = {"at": time.monotonic(), "index": None, "barge_in": barge_in}

    def mark_agent_speech_start(self) -> None:
        # Idempotent while already speaking: more than one LiveKit event can
        # signal the same utterance starting, and restarting the clock on the
        # second one silently under-reports how long the agent actually spoke.
        if self._agent_speaking:
            return
        self._agent_speaking = True
        self._agent_speech_started = time.monotonic()
        turn = self._turn_open
        if not turn or turn["index"] is not None:
            return
        turn["index"] = len(self.metrics)
        self.metrics.append(
            TurnMetric(
                response_ms=int((time.monotonic() - turn["at"]) * 1000),
                barge_in=turn["barge_in"],
            )
        )
        self._emit()

    def mark_agent_speech_end(self) -> None:
        self._agent_speaking = False
        if self._agent_speech_started is None:
            return
        talk = int((time.monotonic() - self._agent_speech_started) * 1000)
        self._agent_speech_started = None
        # Session total, not per-turn: the opening greeting answers no question,
        # so attributing it to a turn would either lose it or distort that turn.
        self.total_talk_ms += talk
        turn = self._turn_open
        if turn and turn["index"] is not None:
            row = self.metrics[turn["index"]]
            row.talk_ms = (row.talk_ms or 0) + talk
        self._emit()

    def metrics_summary(self) -> dict[str, Any]:
        """Interrupted turns are reported but excluded from the averages: the
        agent was cut off mid-sentence, so the interval no longer describes how
        long the system took to respond."""
        clean = [m.response_ms for m in self.metrics if not m.barge_in and m.response_ms is not None]
        elapsed_ms = int((time.time() - self.started_at) * 1000)
        return {
            "turns": len(self.metrics),
            "avgResponseMs": round(sum(clean) / len(clean)) if clean else None,
            "slowestMs": max(clean) if clean else None,
            "bargeIns": sum(1 for m in self.metrics if m.barge_in),
            "agentTalkMs": self.total_talk_ms,
            "talkSharePct": round(self.total_talk_ms / elapsed_ms * 100) if elapsed_ms else 0,
            "scripts": sorted(self.languages, key=self.languages.get, reverse=True),
            "rows": [m.to_dict() for m in self.metrics],
        }

    # -- output ------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        ok, reasons = self.can_confirm()
        return {
            "callId": self.call_id,
            "indent": self.state.to_dict(),
            "plain": self.state.to_plain(),
            "issues": [
                {"field": i.field, "message": i.message, "severity": i.severity}
                for i in self.issues()
            ],
            "canConfirm": ok,
            "blockedBy": reasons,
            "metrics": self.metrics_summary(),
            "transcript": [u.to_dict() for u in self.transcript[-50:]],
        }

    def _emit(self) -> None:
        if self.on_change:
            self.on_change(self.snapshot())
