"""Unofficial LiveKit Agents plugin for Sarvam AI (Saaras STT + Bulbul TTS).

No official `livekit-plugins-sarvam` package exists (see roadmap §4, Phase 1) — this
is modeled on the structure of `livekit-plugins-soniox` and `livekit-plugins-cartesia`,
against Sarvam's documented WebSocket protocols (docs.sarvam.ai, checked Aug 2026).

The LLM leg does NOT need a plugin here: Sarvam's chat completions endpoint is
OpenAI-compatible, so `livekit.plugins.openai.LLM(base_url="https://api.sarvam.ai/v1")`
covers it directly — see ../agent.py.
"""

from .stt import STT, STTOptions
from .tts import TTS, TTSOptions

__all__ = ["STT", "STTOptions", "TTS", "TTSOptions"]
