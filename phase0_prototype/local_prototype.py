"""Phase 0 — prove the Sarvam pipeline before touching LiveKit at all.

No rooms, no tokens, no clients. This talks to Sarvam's STT/LLM/TTS APIs
directly and answers the four questions the roadmap says gate everything
downstream (see voiceaiselfhostroadmap.md §4, Phase 0):

  1. Does Saaras/the LLM handle real Hindi/Hinglish logistics phrases?
  2. Which Bulbul v3 speaker wins the A/B?
  3. What's the real character-count-per-minute for TTS cost (replaces the
     ₹1.35/min estimate in the roadmap's §1 with a measured number)?
  4. What's Sarvam-105B's own latency? (the one number the roadmap doesn't have)

Three modes, so you don't need a microphone/PortAudio working to get the
one measurement that matters most (LLM latency):

    python local_prototype.py --batch          # types TEST_PHRASES at the LLM, no mic needed
    python local_prototype.py --voice-ab        # synthesizes AB_TEST_REPLIES with each candidate
                                                 # speaker, saves .mp3 files under output/ for you
                                                 # to listen to, and reports the real char/min rate
    python local_prototype.py --mode mic        # full loop: mic -> Saaras streaming STT -> LLM -> TTS

Playback: synthesized audio is saved to output/*.mp3 rather than played
back live in this script. Getting mp3 decode+playback right cross-platform
is exactly the kind of throwaway plumbing that isn't worth building twice —
real-time playback comes for free once this is wired into LiveKit (Phase 1b).
Listen to the files directly for the voice A/B.

Requires SARVAM_API_KEY (see ../.env.example). Uncertain protocol details
(STT client-message shape) are flagged inline and in docs/OPEN_QUESTIONS.md —
confirm against a live connection before trusting this in production.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import os
import time
import wave
from pathlib import Path

from dotenv import load_dotenv
from sarvamai import AsyncSarvamAI

from test_phrases import AB_TEST_REPLIES, CANDIDATE_SPEAKERS, SYSTEM_PROMPT, TEST_PHRASES

load_dotenv()

API_KEY = os.environ.get("SARVAM_API_KEY")
LANGUAGE_CODE = os.environ.get("SARVAM_LANGUAGE_CODE", "hi-IN")
LLM_MODEL = os.environ.get("SARVAM_LLM_MODEL", "sarvam-105b-conversations")
# Same var the LiveKit agent reads, so prototype and production speak in one voice.
# --voice-ab deliberately ignores this and sweeps CANDIDATE_SPEAKERS instead.
TTS_SPEAKER = os.environ.get("SARVAM_TTS_SPEAKER", CANDIDATE_SPEAKERS[0])
OUTPUT_DIR = Path(__file__).parent / "output"

SAMPLE_RATE = 16000
MIC_CHUNK_SECONDS = 0.2  # how much audio we batch before sending a chunk to STT


def require_api_key() -> str:
    if not API_KEY:
        raise SystemExit(
            "SARVAM_API_KEY is not set. Copy ../.env.example to .env, fill in your key from "
            "dashboard.sarvam.ai, and re-run (this script loads .env automatically)."
        )
    return API_KEY


def pcm16_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw PCM16 mono samples in a minimal WAV container.

    The Sarvam Python SDK's streaming `encoding` param is documented as fixed to
    "audio/wav" — see docs/OPEN_QUESTIONS.md. Wrapping each small chunk as its own
    WAV is our best-effort reading of that constraint for continuous mic streaming;
    confirm against a live connection before relying on it.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


async def run_llm_turn(client: AsyncSarvamAI, user_text: str) -> tuple[str, float]:
    """Send one turn to Sarvam's chat completions endpoint, return (reply, latency_ms).

    This times the full completion, not strictly time-to-first-token (the roadmap's
    own Phase 0 sketch measured the same thing). Sarvam's endpoint does support
    `stream=True` for SSE if you want to tighten this to a true TTFT number later.
    """
    t0 = time.perf_counter()
    response = await client.chat.completions(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        max_tokens=80,
    )
    latency_ms = (time.perf_counter() - t0) * 1000
    reply = response.choices[0].message.content
    return reply, latency_ms


async def run_tts_turn(
    client: AsyncSarvamAI, text: str, speaker: str, out_path: Path
) -> tuple[int, float]:
    """Synthesize `text` with `speaker`, save to out_path, return (char_count, latency_ms)."""
    from sarvamai import AudioOutput  # local import: only needed here

    t0 = time.perf_counter()
    audio_bytes = bytearray()
    async with client.text_to_speech_streaming.connect(model="bulbul:v3") as ws:
        # sarvamai>=0.1.30 names this target_language_code, not language_code.
        await ws.configure(target_language_code=LANGUAGE_CODE, speaker=speaker)
        await ws.convert(text)
        await ws.flush()
        while True:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                break
            if isinstance(message, AudioOutput):
                audio_bytes += base64.b64decode(message.data.audio)
    latency_ms = (time.perf_counter() - t0) * 1000

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio_bytes)
    return len(text), latency_ms


async def cmd_batch(client: AsyncSarvamAI) -> None:
    """Feed TEST_PHRASES straight to the LLM (no mic, no STT) — the fastest way to
    get the one number Phase 0 is missing: Sarvam-105B's real latency, plus a first
    read on whether it handles logistics Hindi/Hinglish sensibly."""
    print(f"Model: {LLM_MODEL}  |  {len(TEST_PHRASES)} phrases\n")
    latencies = []
    for phrase, note in TEST_PHRASES:
        reply, latency_ms = await run_llm_turn(client, phrase)
        latencies.append(latency_ms)
        print(f"[{note}]")
        print(f"  driver: {phrase}")
        print(f"  agent : {reply}")
        print(f"  LLM latency: {latency_ms:.0f}ms\n")

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    print(f"--- LLM latency: min={min(latencies):.0f}ms  p50={p50:.0f}ms  max={max(latencies):.0f}ms ---")
    print("Judge the replies above for logistics-domain sense and code-mixing handling.")
    print("If p50 is uncomfortably high, that's a Phase-0 problem per the roadmap — not a Phase-3 surprise.")


async def cmd_voice_ab(client: AsyncSarvamAI) -> None:
    """Synthesize AB_TEST_REPLIES with each CANDIDATE_SPEAKERS voice, save to output/,
    and report the real characters-per-minute-of-agent-speech figure that should
    replace the ₹1.35/min TTS estimate in the roadmap's §1."""
    total_chars = 0
    total_latency_ms = 0.0
    for speaker in CANDIDATE_SPEAKERS:
        print(f"\n=== speaker: {speaker} ===")
        for i, reply in enumerate(AB_TEST_REPLIES):
            out_path = OUTPUT_DIR / f"{speaker}_{i}.mp3"
            chars, latency_ms = await run_tts_turn(client, reply, speaker, out_path)
            total_chars += chars
            total_latency_ms += latency_ms
            print(f"  [{i}] {chars} chars, {latency_ms:.0f}ms -> {out_path}")

    avg_chars_per_reply = total_chars / (len(CANDIDATE_SPEAKERS) * len(AB_TEST_REPLIES))
    print(f"\n--- Listen to output/*.mp3 and pick a winner ---")
    print(f"Avg chars/reply: {avg_chars_per_reply:.0f}")
    print(
        "To turn this into a real ₹/min figure: take your actual expected replies-per-call-minute "
        "from a real transcript sample (roadmap assumed ~450 chars/min of agent speech at 50% "
        "talk time) and multiply by ₹3/1,000 chars (Bulbul's rate). This script gives you the "
        "chars/reply half of that equation with your own reply text; the calls-per-minute half "
        "needs real call data."
    )


async def cmd_text_loop(client: AsyncSarvamAI) -> None:
    """Interactive: type what the driver would say, get LLM + TTS timing per turn."""
    print("Type a driver utterance (Hindi/Hinglish OK), or 'quit'. Ctrl+C also exits.\n")
    while True:
        try:
            user_text = input("driver> ").strip()
        except EOFError:
            break
        if not user_text or user_text.lower() in {"quit", "exit"}:
            break

        reply, llm_ms = await run_llm_turn(client, user_text)
        print(f"agent : {reply}  [LLM {llm_ms:.0f}ms]")

        out_path = OUTPUT_DIR / "last_reply.mp3"
        chars, tts_ms = await run_tts_turn(client, reply, TTS_SPEAKER, out_path)
        print(f"        [TTS {tts_ms:.0f}ms, {chars} chars -> {out_path}]\n")


async def cmd_mic_loop(client: AsyncSarvamAI) -> None:
    """Full loop: mic -> Saaras streaming STT -> LLM -> TTS (saved to file).

    Requires `sounddevice` + a working PortAudio install, which this environment
    can't verify for you. If import/device errors show up, `--batch` and the
    interactive text mode above cover the LLM/TTS legs without a mic.
    """
    import numpy as np
    import sounddevice as sd

    print("Listening... speak a driver phrase, then pause (VAD end-of-speech triggers the turn).")
    print("Ctrl+C to stop.\n")

    audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _on_audio(indata, frames, time_info, status):  # sounddevice callback, sync context
        if status:
            print(f"[mic status] {status}")
        loop.call_soon_threadsafe(audio_queue.put_nowait, bytes(indata))

    chunk_frames = int(SAMPLE_RATE * MIC_CHUNK_SECONDS)
    stream = sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=chunk_frames,
        dtype="int16",
        channels=1,
        callback=_on_audio,
    )

    async with client.speech_to_text_streaming.connect(
        model="saaras:v3",
        mode="transcribe",
        language_code=LANGUAGE_CODE,
        high_vad_sensitivity=True,
        vad_signals=True,
    ) as ws:

        async def send_audio() -> None:
            while True:
                pcm_chunk = await audio_queue.get()
                wav_bytes = pcm16_to_wav_bytes(pcm_chunk)
                b64 = base64.b64encode(wav_bytes).decode("ascii")
                await ws.transcribe(audio=b64, encoding="audio/wav", sample_rate=SAMPLE_RATE)

        send_task = asyncio.create_task(send_audio())
        stream.start()

        last_transcript = ""
        try:
            async for message in ws:
                if message.type == "events":
                    signal = message.data.signal_type
                    if signal == "END_SPEECH" and last_transcript:
                        print(f"driver (final): {last_transcript}")
                        t_stt_done = time.perf_counter()

                        reply, llm_ms = await run_llm_turn(client, last_transcript)
                        print(f"agent : {reply}  [LLM {llm_ms:.0f}ms]")

                        out_path = OUTPUT_DIR / f"turn_{int(t_stt_done)}.mp3"
                        chars, tts_ms = await run_tts_turn(
                            client, reply, TTS_SPEAKER, out_path
                        )
                        print(f"        [TTS {tts_ms:.0f}ms, {chars} chars -> {out_path}]")
                        print(f"        [end-of-speech -> reply ready: {llm_ms + tts_ms:.0f}ms]\n")

                        last_transcript = ""
                elif message.type == "data":
                    last_transcript = message.data.transcript
                    print(f"  ...{last_transcript}", end="\r")
        except KeyboardInterrupt:
            pass
        finally:
            stream.stop()
            stream.close()
            send_task.cancel()


async def main() -> None:
    require_api_key()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["text", "mic"], default="text")
    parser.add_argument("--batch", action="store_true", help="run TEST_PHRASES through the LLM non-interactively")
    parser.add_argument("--voice-ab", action="store_true", help="A/B the candidate Bulbul speakers")
    args = parser.parse_args()

    client = AsyncSarvamAI(api_subscription_key=API_KEY)

    if args.voice_ab:
        await cmd_voice_ab(client)
    elif args.batch:
        await cmd_batch(client)
    elif args.mode == "mic":
        await cmd_mic_loop(client)
    else:
        await cmd_text_loop(client)


if __name__ == "__main__":
    asyncio.run(main())
