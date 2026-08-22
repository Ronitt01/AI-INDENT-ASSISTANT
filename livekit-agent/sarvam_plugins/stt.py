# Unofficial Sarvam AI STT adapter for LiveKit Agents.
#
# Structure modeled on livekit-plugins-soniox (same shape of problem: persistent
# websocket, VAD-driven endpointing, reconnect-on-drop). Protocol details (URL,
# query params, message shapes) are from docs.sarvam.ai, checked Aug 2026 — see
# docs/OPEN_QUESTIONS.md for the one inconsistency in Sarvam's own docs (the client
# audio-message shape) that's worth confirming against a live connection before
# trusting this in production. This is new code, not a tested integration.

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import wave
from dataclasses import dataclass
from urllib.parse import urlencode

import aiohttp

from livekit import rtc
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIError,
    APIStatusError,
    APITimeoutError,
    LanguageCode,
    stt,
    utils,
)
from livekit.agents.stt import SpeechEventType
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import is_given

from .log import logger

BASE_WS_URL = "wss://api.sarvam.ai/speech-to-text/ws"


@dataclass
class STTOptions:
    """See https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe/ws"""

    model: str = "saaras:v3"
    mode: str = "transcribe"  # transcribe | translate | verbatim | translit | codemix
    language_code: str = "hi-IN"
    sample_rate: int = 16000  # 16000 or 8000 only
    #: Keep this True. It is tempting to turn off: at True Sarvam emits END_SPEECH on
    #: every short pause, so one sentence arrives as several segments (measured: 3 for
    #: "Chandigarh se Mumbai deliver karna hai, material steel ka hai, bees ton").
    #: But END_SPEECH is the ONLY thing that makes this adapter emit a final transcript,
    #: and at False a live call produced no END_SPEECH at all - the caller's words showed
    #: up as interim text in the console and then nothing happened: no final, no user
    #: turn, no LLM call, an empty indent and "0.0s STT" in the call log. Fragmentation
    #: is handled where it belongs instead: the segments are accumulated below, and
    #: LiveKit's endpointing delay decides when the turn is actually over.
    high_vad_sensitivity: bool = True
    vad_signals: bool = True
    #: How much audio to accumulate before sending it as one WAV chunk.
    #:
    #: MEASURED, not guessed. LiveKit delivers ~10-20ms frames; sending each as its
    #: own complete WAV file makes Sarvam transcribe each fragment independently and
    #: discard most of the speech - a whole spoken sentence came back as the single
    #: words "और।" / "ਸਾਡੀ।" / "Occasion". Costs up to this much added latency on the
    #: STT leg, which the budget can absorb; losing most of the driver's words cannot.
    chunk_ms: int = 200
    #: Commit the turn this long after the last transcript segment arrives.
    #:
    #: Sarvam only emits END_SPEECH once NEW audio marks the boundary, so while the
    #: caller is silent nothing closes their turn: the sentence sits in the console as
    #: interim text and is only delivered when they speak again - even an "hmm" flushes
    #: it. The whole conversation runs one turn behind. This timer closes the turn from
    #: our side instead of waiting for a signal that only arrives too late. Keep it
    #: below the session's endpointing min_delay so the final lands first and LiveKit
    #: still decides when to reply.
    finalize_after_silence_ms: int = 700


class STT(stt.STT):
    """Speech-to-Text using Sarvam AI's Saaras streaming API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = BASE_WS_URL,
        http_session: aiohttp.ClientSession | None = None,
        params: STTOptions | None = None,
    ) -> None:
        params = params or STTOptions()
        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=True,
                interim_results=True,
                offline_recognize=False,
            )
        )
        self._api_key = api_key or os.getenv("SARVAM_API_KEY")
        if not self._api_key:
            raise ValueError("Sarvam API key is required. Set SARVAM_API_KEY or pass api_key")
        self._base_url = base_url
        self._http_session = http_session
        self._params = params

    @property
    def model(self) -> str:
        return self._params.model

    @property
    def provider(self) -> str:
        return "Sarvam"

    async def _recognize_impl(
        self,
        buffer: utils.AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ) -> stt.SpeechEvent:
        raise NotImplementedError(
            "Sarvam STT adapter only implements streaming recognition; use .stream()"
        )

    def stream(
        self,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> SpeechStream:
        return SpeechStream(stt=self, conn_options=conn_options, language=language)


class SpeechStream(stt.SpeechStream):
    def __init__(
        self,
        *,
        stt: STT,
        conn_options: APIConnectOptions,
        language: NotGivenOr[str] = NOT_GIVEN,
    ) -> None:
        super().__init__(stt=stt, conn_options=conn_options, sample_rate=stt._params.sample_rate)
        self._stt: STT = stt
        self._language = language if is_given(language) else stt._params.language_code
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reconnect_event = asyncio.Event()
        # Shared between the send and receive tasks: the receive task appends Sarvam's
        # incremental segments here, and EITHER task may finalise it (see _emit_final).
        self._pending_transcript = ""
        self._is_speaking = False
        self._last_segment_at: float | None = None

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._stt._http_session:
            self._stt._http_session = utils.http_context.http_session()
        return self._stt._http_session

    async def _connect_ws(self) -> aiohttp.ClientWebSocketResponse:
        p = self._stt._params
        query = urlencode(
            {
                "language-code": self._language,
                "model": p.model,
                "mode": p.mode,
                "sample_rate": p.sample_rate,
                "high_vad_sensitivity": str(p.high_vad_sensitivity).lower(),
                "vad_signals": str(p.vad_signals).lower(),
                "input_audio_codec": "wav",
            }
        )
        url = f"{self._stt._base_url}?{query}"
        ws = await asyncio.wait_for(
            self._ensure_session().ws_connect(
                url, headers={"Api-Subscription-Key": self._stt._api_key}
            ),
            timeout=self._conn_options.timeout,
        )
        logger.debug("Sarvam STT WebSocket connection established")
        return ws

    async def _run(self) -> None:
        while True:
            try:
                ws = await self._connect_ws()
                self._ws = ws
                tasks = [
                    asyncio.create_task(self._send_audio_task()),
                    asyncio.create_task(self._recv_messages_task()),
                    asyncio.create_task(self._silence_watchdog_task()),
                ]
                wait_reconnect_task = asyncio.create_task(self._reconnect_event.wait())
                tasks_group = asyncio.gather(*tasks)
                try:
                    done, _ = await asyncio.wait(
                        [tasks_group, wait_reconnect_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in done:
                        if task is not wait_reconnect_task:
                            task.result()
                    if wait_reconnect_task not in done:
                        break
                    self._reconnect_event.clear()
                finally:
                    await utils.aio.gracefully_cancel(*tasks, wait_reconnect_task)
                    tasks_group.cancel()
                    tasks_group.exception()
            except APIError:
                raise
            except asyncio.TimeoutError as e:
                raise APITimeoutError("Timeout connecting to Sarvam STT") from e
            except aiohttp.ClientResponseError as e:
                raise APIStatusError(
                    message=e.message, status_code=e.status, request_id=None, body=None
                ) from e
            except aiohttp.ClientError as e:
                raise APIConnectionError(f"Sarvam STT connection error: {e}") from e
            finally:
                if self._ws is not None:
                    await self._ws.close()
                    self._ws = None

    async def _silence_watchdog_task(self) -> None:
        """Close the turn once the caller has been quiet for finalize_after_silence_ms."""
        loop = asyncio.get_running_loop()
        threshold = self._stt._params.finalize_after_silence_ms / 1000
        while True:
            await asyncio.sleep(0.1)
            if not self._pending_transcript or self._last_segment_at is None:
                continue
            if loop.time() - self._last_segment_at >= threshold:
                logger.info("STT silence timeout -> closing turn")
                self._emit_final()

    def _emit_final(self) -> None:
        """Commit whatever has been transcribed so far as one user turn.

        Called from two places, because neither signal is reliable alone:

        * Sarvam's END_SPEECH - fires on pauses, but in a live call the mic never goes
          properly silent, so it may never fire at all. Relying on it alone left the
          caller's words accumulating as interim text forever: the console showed the
          full sentence while the agent saw no turn, no LLM call and an empty indent.
        * LiveKit's end-of-input sentinel - its VAD and turn detector already decided
          the caller stopped. That is the authoritative signal in this architecture,
          so it must be able to close the turn even if Sarvam stays quiet.

        Idempotent: whichever fires first commits, the other finds nothing pending.
        """
        text = self._pending_transcript.strip()
        self._pending_transcript = ""
        self._is_speaking = False
        self._last_segment_at = None
        logger.info("STT finalise: %r", text[:80] if text else "(nothing pending)")
        if not text:
            return
        self._event_ch.send_nowait(
            stt.SpeechEvent(
                type=SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[
                    stt.SpeechData(language=LanguageCode(self._language), text=text)
                ],
            )
        )
        self._event_ch.send_nowait(stt.SpeechEvent(type=SpeechEventType.END_OF_SPEECH))

    async def _send_audio_task(self) -> None:
        """Forward LiveKit PCM frames to Sarvam as base64 WAV chunks.

        Frames are ACCUMULATED to `chunk_ms` before sending. Sending each LiveKit
        frame as its own complete WAV file makes Sarvam treat every 10-20ms
        fragment as a standalone utterance and return one word for it: a full
        spoken sentence came back as "और।", "ਸਾਡੀ।", "Occasion" - most of the
        speech discarded. See STTOptions.chunk_ms.

        Sarvam's SDK documents `encoding` as fixed to "audio/wav" and there is no
        confirmed raw-PCM streaming shape, so each accumulated chunk is wrapped in
        a minimal WAV header.
        """
        if not self._ws:
            return

        chunk_ms = self._stt._params.chunk_ms
        rate = self._stt._params.sample_rate
        pending = bytearray()

        async def send_pending() -> None:
            if not pending or self._ws is None:
                return
            b64 = base64.b64encode(_pcm16_to_wav(bytes(pending), rate)).decode("ascii")
            pending.clear()
            # `audio` must be a NESTED object, not a bare base64 string. The flat
            # shape (from Sarvam's API-reference page) is rejected by the live
            # service with: 'audio: Input should be a valid dictionary or instance
            # of AudioContent'. The docs' streaming-tutorial/SDK shape is the
            # correct one — this resolves the inconsistency flagged in
            # docs/OPEN_QUESTIONS.md, verified against a live connection Aug 2026.
            await self._ws.send_json(
                {"audio": {"data": b64, "sample_rate": rate, "encoding": "audio/wav"}}
            )

        async for data in self._input_ch:
            if isinstance(data, rtc.AudioFrame):
                rate = data.sample_rate
                pending += data.data.tobytes()
                if len(pending) >= int(rate * 2 * chunk_ms / 1000):  # 2 bytes/sample, mono
                    await send_pending()
            else:
                # flush sentinel: ask Sarvam to finalize whatever it's holding.
                # Buffered audio has to go FIRST, or the tail of the utterance is
                # finalised without ever having been sent.
                await send_pending()
                await self._ws.send_json({"type": "flush"})
                logger.info("STT flush sentinel from LiveKit")
                # LiveKit says the caller stopped. Ask Sarvam to finalise, then commit
                # the turn ourselves rather than waiting for an END_SPEECH that may
                # never arrive on a live, never-quite-silent microphone.
                self._emit_final()

        # Stream ended: don't strand a partial chunk.
        await send_pending()

    async def _recv_messages_task(self) -> None:
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    break
                if msg.type != aiohttp.WSMsgType.TEXT:
                    logger.warning(f"Unexpected message type from Sarvam STT: {msg.type}")
                    continue

                content = json.loads(msg.data)
                msg_type = content.get("type")
                data = content.get("data", {}) or {}

                if msg_type == "events":
                    signal = data.get("signal_type")
                    logger.info("STT sarvam signal: %s", signal)
                    if signal == "START_SPEECH" and not self._is_speaking:
                        self._is_speaking = True
                        self._event_ch.send_nowait(
                            stt.SpeechEvent(type=SpeechEventType.START_OF_SPEECH)
                        )
                    elif signal == "END_SPEECH":
                        self._emit_final()
                elif msg_type == "data":
                    transcript = data.get("transcript", "")
                    if transcript:
                        # ACCUMULATE, do not replace. Sarvam sends incremental segments,
                        # not a cumulative running transcript, so overwriting keeps only
                        # the last fragment: a three-part sentence arrived as "20 टन।"
                        # with the first two thirds silently discarded. Joining the
                        # segments reproduces the sentence verbatim (verified live).
                        self._pending_transcript = (
                            f"{self._pending_transcript} {transcript}".strip()
                        )
                        self._last_segment_at = asyncio.get_running_loop().time()
                        self._event_ch.send_nowait(
                            stt.SpeechEvent(
                                type=SpeechEventType.INTERIM_TRANSCRIPT,
                                alternatives=[
                                    stt.SpeechData(
                                        language=LanguageCode(self._language),
                                        text=self._pending_transcript,
                                    )
                                ],
                            )
                        )
                elif msg_type == "error":
                    code = data.get("code", -1)
                    message = data.get("message", "Unknown Sarvam STT error")
                    logger.error(f"Sarvam STT error {code}: {message}")
                    raise APIStatusError(
                        f"Sarvam STT error: {code} - {message}",
                        status_code=code if isinstance(code, int) else -1,
                        body=content,
                    )

        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Sarvam STT WebSocket error while receiving: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in Sarvam STT recv loop: {e}")

        if not self._reconnect_event.is_set():
            logger.warning("Sarvam STT WebSocket closed; requesting reconnect")
            self._reconnect_event.set()


def _pcm16_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()
