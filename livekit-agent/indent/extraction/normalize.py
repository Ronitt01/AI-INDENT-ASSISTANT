"""Text folding and script detection.

Everything downstream matches against normalised text, and the lexicon's terms
are normalised at build time by the equivalent JS routine. If the two ever drift
apart, terms stop matching silently — so this module is deliberately small and
its behaviour is pinned by tests.
"""

from __future__ import annotations

import re
import unicodedata

from .lexicon import LEXICON

_ZERO_WIDTH = re.compile(r"[​-‏﻿­]")
#: Danda, double danda, Urdu stops, Arabic comma and friends.
_NATIVE_PUNCT = re.compile(r"[।॥۔،؛؟٫٬…‥܍]")
#: Sentence punctuation becomes whitespace — except a '.' or ',' between digits,
#: which is a decimal or thousands separator ("1.5 tons").
_SENTENCE_PUNCT = re.compile(r"(?<![0-9])[.,](?![0-9])|[!?;:\"'()\[\]{}]")

_DIGIT_MAP: dict[str, str] = dict(LEXICON.get("digitMap", {}))
_DIGIT_RE = re.compile("[" + re.escape("".join(_DIGIT_MAP)) + "]") if _DIGIT_MAP else None


def normalize(text: str | None) -> str:
    """Fold a transcript chunk into the form the matchers expect.

    NFC, native numerals mapped to ASCII, native and sentence punctuation turned
    into whitespace, lowercased, whitespace collapsed.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    s = _ZERO_WIDTH.sub("", s)
    if _DIGIT_RE is not None:
        s = _DIGIT_RE.sub(lambda m: _DIGIT_MAP.get(m.group(0), m.group(0)), s)
    s = _NATIVE_PUNCT.sub(" ", s)
    s = _SENTENCE_PUNCT.sub(" ", s)
    s = s.lower()
    return re.sub(r"\s+", " ", s).strip()


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?۔।॥])\s+")


def strip_questions(raw: str) -> str:
    """Drop interrogative sentences from agent speech.

    An agent asking "truck, trailer, or tanker?" is listing options, not
    confirming one, but the words are identical to an answer. Splitting sentence
    by sentence means a mixed utterance still yields its statement half.
    """
    parts = [p for p in _SENTENCE_SPLIT.split(str(raw or "")) if p]
    kept = [p for p in parts if not re.search(r"[?؟]\s*$", p.strip())]
    return " ".join(kept).strip()


#: Script ranges, ordered so the most specific Indic blocks are tested before Latin.
_SCRIPTS: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    ("hi", "Hindi / Marathi", "Devanagari", re.compile(r"[ऀ-ॿ]")),
    ("pa", "Punjabi", "Gurmukhi", re.compile(r"[਀-੿]")),
    ("gu", "Gujarati", "Gujarati", re.compile(r"[઀-૿]")),
    ("bn", "Bengali", "Bengali", re.compile(r"[ঀ-৿]")),
    ("ta", "Tamil", "Tamil", re.compile(r"[஀-௿]")),
    ("te", "Telugu", "Telugu", re.compile(r"[ఀ-౿]")),
    ("kn", "Kannada", "Kannada", re.compile(r"[ಀ-೿]")),
    ("ml", "Malayalam", "Malayalam", re.compile(r"[ഀ-ൿ]")),
    ("ur", "Urdu", "Arabic", re.compile(r"[؀-ۿݐ-ݿ]")),
    ("en", "English", "Latin", re.compile(r"[A-Za-z]")),
)


def detect_script(text: str) -> dict[str, str] | None:
    """Dominant script of a transcript, or None if it carries no letters.

    Sarvam reports the language it was *configured* with, not necessarily what
    the caller used. The script the text came back in is direct evidence and is
    always available, so the console labels this as script-derived rather than
    claiming it is the engine's own language decision.
    """
    s = str(text or "")
    best: tuple[str, str, str] | None = None
    best_count = 0
    for code, label, script, pattern in _SCRIPTS:
        count = len(pattern.findall(s))
        if count > best_count:
            best_count, best = count, (code, label, script)
    if not best or best_count == 0:
        return None
    return {"code": best[0], "label": best[1], "script": best[2]}
