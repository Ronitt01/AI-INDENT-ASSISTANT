"""A rolling buffer of recent transcript chunks for one speaker.

STT emits a few words at a time, so matching has to run over the joined tail
rather than each chunk alone — otherwise "21/." and "September" arrive as
separate events and never form a date.

Bounded two ways: by chunk count, so an old sentence eventually falls out of
scope, and by character count, so one very long utterance cannot grow the window
without limit.
"""

from __future__ import annotations


class TranscriptWindow:
    def __init__(self, max_chunks: int = 8, max_chars: int = 600) -> None:
        self.max_chunks = max_chunks
        self.max_chars = max_chars
        self.chunks: list[str] = []

    def push(self, text: str) -> str:
        """Add a chunk and return the joined window."""
        chunk = (text or "").strip()
        if chunk:
            self.chunks.append(chunk)
        while len(self.chunks) > self.max_chunks:
            self.chunks.pop(0)
        while len(" ".join(self.chunks)) > self.max_chars and len(self.chunks) > 1:
            self.chunks.pop(0)
        return self.text()

    def text(self) -> str:
        return " ".join(self.chunks)

    def clear(self) -> None:
        self.chunks = []
