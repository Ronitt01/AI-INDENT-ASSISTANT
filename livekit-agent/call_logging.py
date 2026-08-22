"""Phase 5 — transcripts, cost, latency, and error visibility.

Vapi gave you all of this for free on a dashboard. Self-hosting means it's on you —
this module is the "on you" part: one SQLite file with four tables, wired into
agent.py's session event handlers. Swap DB_PATH for a real Postgres DSN and the
sqlite3 calls for your driver of choice when you outgrow a single file; the schema
doesn't need to change to do that.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("call_logging")

DB_PATH = Path(os.getenv("CALL_LOG_DB", Path(__file__).parent / "call_logs.sqlite3"))

# Roadmap §1 rates (INR), verbatim from Sarvam's pricing card as of 16 Aug 2026.
# Recompute these if Sarvam's pricing changes — see docs/OPEN_QUESTIONS.md.
RATE_STT_PER_SECOND = 30 / 3600  # Saaras: ₹30/hour streaming
RATE_TTS_PER_CHAR = 3 / 1000  # Bulbul: ₹3/1,000 chars
RATE_LLM_PROMPT_PER_TOKEN = 29.28 / 1_000_000  # Sarvam-105B input
RATE_LLM_CACHED_PER_TOKEN = 10.98 / 1_000_000  # Sarvam-105B cached input
RATE_LLM_COMPLETION_PER_TOKEN = 73.20 / 1_000_000  # Sarvam-105B output

_SCHEMA = """
CREATE TABLE IF NOT EXISTS call_transcripts (
    session_id TEXT, room TEXT, seq INTEGER, role TEXT, text TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS call_latencies (
    session_id TEXT, room TEXT, metric_type TEXT, duration_ms REAL, ttfb_ms REAL,
    audio_duration_s REAL, characters_count INTEGER, created_at REAL
);
CREATE TABLE IF NOT EXISTS call_costs (
    session_id TEXT PRIMARY KEY, room TEXT,
    stt_seconds REAL DEFAULT 0, tts_chars INTEGER DEFAULT 0,
    llm_prompt_tokens INTEGER DEFAULT 0, llm_cached_tokens INTEGER DEFAULT 0,
    llm_completion_tokens INTEGER DEFAULT 0, cost_inr REAL DEFAULT 0,
    started_at REAL, ended_at REAL
);
CREATE TABLE IF NOT EXISTS call_errors (
    session_id TEXT, room TEXT, error TEXT, recoverable INTEGER, created_at REAL
);
"""


def _connect() -> sqlite3.Connection:
    # timeout: WAL still serialises writers, so two concurrent calls finalising at the
    # same moment raise "database is locked" and crash the job (observed with 2 rooms
    # live). Wait for the other writer instead of failing the call.
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _alert(message: str) -> None:
    """Error-visibility stub. Vapi paged you; this doesn't, until you point it
    somewhere. Set SLACK_WEBHOOK_URL and this becomes a real Slack alert with zero
    other changes — that's the "even a Slack webhook is enough at your scale" line
    from the roadmap's Phase 5.
    """
    logger.error(message)
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        return
    try:
        req = urllib.request.Request(
            webhook,
            data=f'{{"text": {message!r}}}'.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except urllib.error.URLError as e:
        logger.error(f"failed to post error alert to Slack webhook: {e}")


class CallRecorder:
    """One instance per call (per LiveKit job/room). Call `finalize()` from the
    session's shutdown callback so the cost row closes out even on an abnormal end."""

    def __init__(self, session_id: str, room: str) -> None:
        init_db()
        self.session_id = session_id
        self.room = room
        self._seq = 0
        self._stt_seconds = 0.0
        self._tts_chars = 0
        self._llm_prompt_tokens = 0
        self._llm_cached_tokens = 0
        self._llm_completion_tokens = 0
        self._cost_inr = 0.0
        self._started_at = time.time()
        with _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO call_costs (session_id, room, started_at) VALUES (?, ?, ?)",
                (session_id, room, self._started_at),
            )

    def record_transcript_item(self, item: object) -> None:
        """item is a livekit.agents.llm.ChatMessage (has .role, .text_content)."""
        role = getattr(item, "role", "unknown")
        text = getattr(item, "text_content", None)
        if not text:
            return
        self._seq += 1
        with _connect() as conn:
            conn.execute(
                "INSERT INTO call_transcripts VALUES (?, ?, ?, ?, ?, ?)",
                (self.session_id, self.room, self._seq, role, text, time.time()),
            )

    def record_metrics(self, m: object) -> None:
        """m is an STTMetrics/TTSMetrics/LLMMetrics from a `metrics_collected` event."""
        metric_type = getattr(m, "type", "unknown")
        with _connect() as conn:
            conn.execute(
                "INSERT INTO call_latencies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.session_id,
                    self.room,
                    metric_type,
                    getattr(m, "duration", 0.0) * 1000,
                    getattr(m, "ttfb", getattr(m, "ttft", -1.0)) * 1000,
                    getattr(m, "audio_duration", 0.0),
                    getattr(m, "characters_count", 0),
                    time.time(),
                ),
            )

        if metric_type == "stt_metrics":
            self._stt_seconds += m.audio_duration
        elif metric_type == "tts_metrics":
            self._tts_chars += m.characters_count
        elif metric_type == "llm_metrics":
            self._llm_prompt_tokens += m.prompt_tokens
            self._llm_cached_tokens += m.prompt_cached_tokens
            self._llm_completion_tokens += m.completion_tokens
        else:
            return
        self._sync_cost()

    def record_error(self, error: str, recoverable: bool) -> None:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO call_errors VALUES (?, ?, ?, ?, ?)",
                (self.session_id, self.room, error, int(recoverable), time.time()),
            )
        if not recoverable:
            _alert(f"[{self.room}] unrecoverable call error: {error}")

    def _sync_cost(self) -> None:
        uncached_prompt_tokens = max(self._llm_prompt_tokens - self._llm_cached_tokens, 0)
        self._cost_inr = (
            self._stt_seconds * RATE_STT_PER_SECOND
            + self._tts_chars * RATE_TTS_PER_CHAR
            + uncached_prompt_tokens * RATE_LLM_PROMPT_PER_TOKEN
            + self._llm_cached_tokens * RATE_LLM_CACHED_PER_TOKEN
            + self._llm_completion_tokens * RATE_LLM_COMPLETION_PER_TOKEN
        )
        with _connect() as conn:
            conn.execute(
                """UPDATE call_costs SET stt_seconds=?, tts_chars=?, llm_prompt_tokens=?,
                   llm_cached_tokens=?, llm_completion_tokens=?, cost_inr=? WHERE session_id=?""",
                (
                    self._stt_seconds,
                    self._tts_chars,
                    self._llm_prompt_tokens,
                    self._llm_cached_tokens,
                    self._llm_completion_tokens,
                    self._cost_inr,
                    self.session_id,
                ),
            )

    def finalize(self) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE call_costs SET ended_at=? WHERE session_id=?",
                (time.time(), self.session_id),
            )
        duration_s = time.time() - self._started_at
        logger.info(
            f"[{self.room}] call finalized: {duration_s:.0f}s wall time, "
            f"{self._stt_seconds:.1f}s STT, {self._tts_chars} TTS chars, "
            f"cost≈₹{self._cost_inr:.3f} ({self._cost_inr / max(duration_s / 60, 1e-6):.2f}/min)"
        )
