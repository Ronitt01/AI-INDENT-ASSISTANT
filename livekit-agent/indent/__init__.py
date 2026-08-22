"""Indent capture domain — pure Python, no LiveKit.

Everything here is unit-testable without a room, a socket, or an API key.
The LiveKit-facing code lives in ``runtime``.
"""

from .domain import (
    Confidence,
    FIELD_BY_KEY,
    FIELD_KEYS,
    FIELDS,
    IndentSession,
    IndentState,
)
from .extraction import TranscriptWindow, detect_fields, detect_script
from .validation import Issue, blocking, resolve_date, resolve_quantity, validate_indent

__all__ = [
    "Confidence", "FIELD_BY_KEY", "FIELD_KEYS", "FIELDS", "IndentSession",
    "IndentState", "TranscriptWindow", "detect_fields", "detect_script",
    "Issue", "blocking", "resolve_date", "resolve_quantity", "validate_indent",
]
