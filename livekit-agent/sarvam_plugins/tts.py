# Unofficial Sarvam AI TTS adapter for LiveKit Agents.
#
# Structure modeled on livekit-plugins-cartesia. Protocol details (URL, config/text/
# flush message shapes) are from docs.sarvam.ai, checked Aug 2026, and are internally
# consistent there (unlike the STT side — see docs/OPEN_QUESTIONS.md).
#
# ASSUMPTION flagged for Phase 0: requests `output_audio_codec: "wav"` so LiveKit's
# AudioEmitter can decode it directly. Sarvam's docs show "mp3" as the *example*
# default; "wav" is documented elsewhere in their API vocabulary (the STT side's
# input_audio_codec) but isn't explicitly confirmed as a valid TTS output value.
# Confirm against a live connection before production — if it 400s, the fallback is
# requesting mp3 and decoding via `livekit.agents.utils.codecs` before pushing frames.

from __future__ import annotations

import asyncio
import base64
import json
import os
from dataclasses import dataclass, field, replace

import aiohttp

from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIError,
    APIStatusError,
    APITimeoutError,
    LanguageCode,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import is_given

from .log import logger

BASE_WS_URL = "wss://api.sarvam.ai/text-to-speech/ws"


# Scripts bulbul:v3 can actually voice, verified against the live API Aug 2026.
# Arabic/Perso-Arabic (Urdu) is deliberately absent: bulbul:v3 rejects it under both
# ur-IN and hi-IN with the same 422 as empty text, so an Urdu reply would kill the call.
_SPEAKABLE_RANGES = (
    (0x0030, 0x0039),                    # digits
    (0x0041, 0x005A), (0x0061, 0x007A),  # Latin (Hinglish, English)
    (0x0900, 0x097F),                    # Devanagari - Hindi, Marathi
    (0x0980, 0x09FF),                    # Bengali
    (0x0A00, 0x0A7F),                    # Gurmukhi - Punjabi
    (0x0A80, 0x0AFF),                    # Gujarati
    (0x0B00, 0x0B7F),                    # Odia
    (0x0B80, 0x0BFF),                    # Tamil
    (0x0C00, 0x0C7F),                    # Telugu
    (0x0C80, 0x0CFF),                    # Kannada
    (0x0D00, 0x0D7F),                    # Malayalam
)


def _is_speakable(text: str) -> bool:
    """True if Sarvam will accept `text` as a synthesis chunk.

    Bulbul returns 422 "Text must contain at least one character from the allowed
    languages" for anything it cannot voice, and the agent turns that into an
    unrecoverable call error the driver hears as silence. Three cases hit this:
    whitespace-only chunks, punctuation-only chunks (a bare "." or "?", which an LLM
    token stream emits routinely), and any script Bulbul does not support (Urdu).
    Filter them out rather than sending and failing.
    Verified live: "." and "?" rejected; "123" and "a" accepted; Urdu rejected.
    """
    return any(lo <= ord(ch) <= hi for ch in text for lo, hi in _SPEAKABLE_RANGES)


@dataclass
class TTSOptions:
    """See https://docs.sarvam.ai/api-reference-docs/text-to-speech/stream"""

    model: str = "bulbul:v3"
    language_code: str = "hi-IN"
    # Default comes from SARVAM_TTS_SPEAKER so the voice is a one-line .env change
    # rather than an edit here; an explicit speaker= argument still overrides it.
    speaker: str = field(default_factory=lambda: os.getenv("SARVAM_TTS_SPEAKER", "shubh"))
    pace: float = 1.0
    sample_rate: int = 24000  # bulbul:v3 default; 22050 for bulbul:v2
    output_audio_codec: str = "wav"  # see module docstring re: this assumption
    # NOTE: the SDK also exposes min_buffer_size (how much text Sarvam buffers before
    # synthesising, which would be the obvious TTFB lever). Do NOT add it here: the live
    # WS API rejects that key in every form tested - int, string, alone, and in the SDK's
    # own exact message shape - with 422 "Input parameters has to be a valid dictionary",
    # which kills the call. The SDK is ahead of the deployed service. max_chunk_length
    # is accepted (verified against the live API Aug 2026).
    max_chunk_length: int = 150
    # Spoken instead of nothing when a whole reply is in a script Bulbul cannot voice.
    # In practice that means Urdu: the LLM keeps answering Urdu speakers in Arabic script
    # however firmly the prompt forbids it (measured: still non-compliant with an explicit
    # rule), and Sarvam's transliteration of Urdu->Devanagari is too poor to speak. Without
    # this the guard drops every chunk and the driver just hears silence.
    unspeakable_fallback: str = "Maaf kijiye, kya aap Hindi ya English mein bata sakte hain?"
    api_key: str = ""


class TTS(tts.TTS):
    """Text-to-Speech using Sarvam AI's Bulbul streaming API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = BASE_WS_URL,
        http_session: aiohttp.ClientSession | None = None,
        params: TTSOptions | None = None,
    ) -> None:
        opts = params or TTSOptions()
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True, aligned_transcript=False),
            sample_rate=opts.sample_rate,
            num_channels=1,
        )
        sarvam_api_key = api_key or os.getenv("SARVAM_API_KEY")
        if not sarvam_api_key:
            raise ValueError("Sarvam API key is required. Set SARVAM_API_KEY or pass api_key")
        opts.api_key = sarvam_api_key

        self._opts = opts
        self._base_url = base_url
        self._session = http_session

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "Sarvam"

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()
        return self._session

    def update_options(
        self,
        *,
        language_code: NotGivenOr[str] = NOT_GIVEN,
        speaker: NotGivenOr[str] = NOT_GIVEN,
        pace: NotGivenOr[float] = NOT_GIVEN,
    ) -> None:
        if is_given(language_code):
            self._opts.language_code = language_code
        if is_given(speaker):
            self._opts.speaker = speaker
        if is_given(pace):
            self._opts.pace = pace

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> ChunkedStream:
        return ChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> SynthesizeStream:
        return SynthesizeStream(tts=self, conn_options=conn_options)

    async def aclose(self) -> None:
        pass


async def _connect_ws(tts_instance: TTS, timeout: float) -> aiohttp.ClientWebSocketResponse:
    url = f"{tts_instance._base_url}?model={tts_instance._opts.model}&send_completion_event=true"
    try:
        ws = await asyncio.wait_for(
            tts_instance._ensure_session().ws_connect(
                url, headers={"Api-Subscription-Key": tts_instance._opts.api_key}
            ),
            timeout,
        )
    except asyncio.TimeoutError:
        raise APITimeoutError() from None
    except aiohttp.ClientResponseError as e:
        raise APIStatusError(
            message=e.message, status_code=e.status, request_id=None, body=None
        ) from None
    except Exception as e:
        raise APIConnectionError(type(e).__name__) from None
    return ws


def _config_message(opts: TTSOptions) -> dict:
    return {
        "type": "config",
        "data": {
            "language_code": opts.language_code,
            "speaker": opts.speaker,
            "model": opts.model,
            "pace": opts.pace,
            "speech_sample_rate": str(opts.sample_rate),
            "output_audio_codec": opts.output_audio_codec,
            "max_chunk_length": opts.max_chunk_length,
        },
    }


class ChunkedStream(tts.ChunkedStream):
    """Non-streaming synthesize(): one text in, one audio blob out, over the same
    WS protocol (Sarvam's non-WS REST-stream endpoint schema isn't confirmed from
    docs — see docs/OPEN_QUESTIONS.md)."""

    def __init__(self, *, tts: TTS, input_text: str, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts: TTS = tts
        self._opts = replace(tts._opts)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        ws = await _connect_ws(self._tts, self._conn_options.timeout)
        try:
            await ws.send_json(_config_message(self._opts))
            text = self._input_text
            has_words = any(ch.isalpha() for ch in text)
            if not _is_speakable(text) and has_words and self._opts.unspeakable_fallback:
                logger.warning("unvoiceable script in synthesize(); using fallback line")
                text = self._opts.unspeakable_fallback
            if _is_speakable(text):
                await ws.send_json({"type": "text", "data": {"text": text}})
            await ws.send_json({"type": "flush"})

            output_emitter.initialize(
                request_id=utils.shortuuid(),
                sample_rate=self._opts.sample_rate,
                num_channels=1,
                mime_type=f"audio/{self._opts.output_audio_codec}",
            )

            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                content = json.loads(msg.data)
                msg_type = content.get("type")
                data = content.get("data", {}) or {}

                if msg_type == "audio":
                    output_emitter.push(base64.b64decode(data["audio"]))
                elif msg_type == "event" and data.get("event_type") == "final":
                    break
                elif msg_type == "error":
                    raise APIStatusError(
                        f"Sarvam TTS error: {data.get('code')} - {data.get('message')}",
                        status_code=data.get("code", -1),
                        body=content,
                    )
        except asyncio.TimeoutError:
            raise APITimeoutError() from None
        except APIError:
            raise
        except aiohttp.ClientError as e:
            raise APIConnectionError(f"Sarvam TTS connection error: {e}") from None
        finally:
            await ws.close()


class SynthesizeStream(tts.SynthesizeStream):
    """Real incremental streaming: one WS connection for the life of the stream,
    pushed text forwarded as Sarvam 'text' messages. Treated as a single segment —
    the framework creates a new SynthesizeStream per utterance, so multi-segment
    handling within one instance (which upstream plugins now deprecate anyway)
    isn't needed here."""

    def __init__(self, *, tts: TTS, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._tts: TTS = tts
        self._opts = replace(tts._opts)

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        request_id = utils.shortuuid()
        ws = await _connect_ws(self._tts, self._conn_options.timeout)

        output_emitter.initialize(
            request_id=request_id,
            sample_rate=self._opts.sample_rate,
            num_channels=1,
            mime_type=f"audio/{self._opts.output_audio_codec}",
            stream=True,
        )
        output_emitter.start_segment(segment_id=request_id)

        async def _send_task() -> None:
            await ws.send_json(_config_message(self._opts))
            saw_words = False  # the LLM produced actual letters, not just punctuation
            sent_text = False  # ...and at least some of it was voiceable
            async for data in self._input_ch:
                if isinstance(data, str):
                    # Only letters count. A stray "." segment must stay silent, not
                    # trigger an apology the driver did not ask for.
                    saw_words = saw_words or any(ch.isalpha() for ch in data)
                    if not _is_speakable(data):
                        continue
                    sent_text = True
                    self._mark_started()
                    await ws.send_json({"type": "text", "data": {"text": data}})
                else:
                    await ws.send_json({"type": "flush"})
            if saw_words and not sent_text and self._opts.unspeakable_fallback:
                logger.warning(
                    "reply was entirely in a script bulbul cannot voice; speaking the "
                    "fallback line instead of going silent"
                )
                self._mark_started()
                await ws.send_json(
                    {"type": "text", "data": {"text": self._opts.unspeakable_fallback}}
                )
            await ws.send_json({"type": "flush"})

        async def _recv_task() -> None:
            async for msg in ws:
                if msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    break
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                content = json.loads(msg.data)
                msg_type = content.get("type")
                data = content.get("data", {}) or {}

                if msg_type == "audio":
                    output_emitter.push(base64.b64decode(data["audio"]))
                elif msg_type == "event" and data.get("event_type") == "final":
                    break
                elif msg_type == "error":
                    raise APIStatusError(
                        f"Sarvam TTS error: {data.get('code')} - {data.get('message')}",
                        status_code=data.get("code", -1),
                        body=content,
                    )

        try:
            tasks = [asyncio.create_task(_send_task()), asyncio.create_task(_recv_task())]
            try:
                await asyncio.gather(*tasks)
            finally:
                await utils.aio.gracefully_cancel(*tasks)
        except asyncio.TimeoutError:
            raise APITimeoutError() from None
        except APIError:
            raise
        except aiohttp.ClientError as e:
            raise APIConnectionError(f"Sarvam TTS connection error: {e}") from None
        finally:
            await ws.close()
