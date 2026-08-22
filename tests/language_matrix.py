"""Language check across the three Sarvam legs the agent depends on.

Per language:
  1. streaming TTS ttfb  (bulbul:v3, 16kHz wav) - the path the agent uses in a call
  2. batch TTS           - clean single WAV, used as the "driver's voice" for STT
  3. STT                 - saaras:v3, mode=transcribe, exactly the agent's config
  4. LLM                 - fed the STT TRANSCRIPT, not the original text, because that
                           is what the agent actually receives mid-call
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import time
import urllib.request

from dotenv import load_dotenv

load_dotenv(r"c:\Users\RONIT\OneDrive\Desktop\vAPI DEMO 2.1\.env")

from sarvamai import AsyncSarvamAI, AudioOutput, SarvamAI

KEY = os.environ["SARVAM_API_KEY"]
SPEAKER = os.environ.get("SARVAM_TTS_SPEAKER", "shubh")
LLM_MODEL = os.environ["SARVAM_LLM_MODEL"]

SYSTEM_PROMPT = (
    "Aap AB Logistics ke liye ek voice assistant hain jo drivers se indent (load booking) "
    "lete hain. Chhote, seedhe jawab dein \u2014 jaise ek dispatcher call par bolta hai, lambi "
    "speeches nahi. Hindi aur Hinglish dono mein baat kar sakte hain, jaisa driver bole."
)

DEV = "\u0928\u093e\u0936\u093f\u0915 \u0938\u0947 \u092a\u0941\u0923\u0947 \u0932\u094b\u0921 \u092d\u0947\u091c\u0928\u093e \u0939\u0948, \u0915\u0932 \u0938\u0941\u092c\u0939 \u0917\u093e\u0921\u093c\u0940 \u091a\u093e\u0939\u093f\u0908"
MAR = "\u0928\u093e\u0936\u093f\u0915\u0939\u0942\u0928 \u092a\u0941\u0923\u094d\u092f\u093e\u0932\u093e \u092e\u093e\u0932 \u092a\u093e\u0920\u0935\u093e\u092f\u091a\u093e \u0906\u0939\u0947, \u0909\u0926\u094d\u092f\u093e \u0938\u0915\u093e\u0933\u0940 \u0917\u093e\u0921\u0940 \u092a\u093e\u0939\u093f\u091c\u0947"
ENG = "I need a truck from Nashik to Pune tomorrow morning for a twenty ton load"
HIN = "Nashik se Pune load bhejna hai, kal subah gaadi chahiye"

# (label, language_code, spoken text, reference for WER or None if script differs)
CASES = [
    ("Hindi (Devanagari)", "hi-IN", DEV, DEV),
    ("Marathi", "mr-IN", MAR, MAR),
    ("English (en-IN)", "en-IN", ENG, ENG),
    ("Hinglish (Latin)", "hi-IN", HIN, None),
]


def words(s: str) -> list[str]:
    return re.sub(r"[^\w\s\u0900-\u097F]", " ", s.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    if not r:
        return 1.0
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            c = 0 if r[i - 1] == h[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c)
    return d[len(r)][len(h)] / len(r)


def llm(text: str) -> tuple[float, str]:
    body = json.dumps({"model": LLM_MODEL, "max_tokens": 80,
                       "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": text}]}).encode()
    req = urllib.request.Request("https://api.sarvam.ai/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {KEY}"})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.load(r)
        return (time.perf_counter() - t) * 1000, (d["choices"][0]["message"]["content"] or "").strip()
    except urllib.error.HTTPError as e:
        return (time.perf_counter() - t) * 1000, f"<<HTTP {e.code}>>"


async def tts_stream_ttfb(client: AsyncSarvamAI, text: str, lang: str) -> float:
    """First-audio-byte latency on the streaming path the agent uses in a call."""
    t = time.perf_counter()
    async with client.text_to_speech_streaming.connect(model="bulbul:v3") as ws:
        await ws.configure(target_language_code=lang, speaker=SPEAKER,
                           output_audio_codec="wav", speech_sample_rate=16000)
        await ws.convert(text)
        await ws.flush()
        while True:
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=8.0)
            except asyncio.TimeoutError:
                return -1
            if isinstance(m, AudioOutput):
                return (time.perf_counter() - t) * 1000


def tts_batch(sync: SarvamAI, text: str, lang: str) -> bytes:
    r = sync.text_to_speech.convert(text=text, language_code=lang,
                                    speaker=SPEAKER, model="bulbul:v3")
    return base64.b64decode(r.audios[0])


def stt(sync: SarvamAI, wav: bytes, lang: str, mode: str = "transcribe") -> tuple[float, str]:
    f = io.BytesIO(wav)
    f.name = "a.wav"
    t = time.perf_counter()
    try:
        r = sync.speech_to_text.transcribe(file=f, model="saaras:v3",
                                           language_code=lang, mode=mode)
        return (time.perf_counter() - t) * 1000, (r.transcript or "").strip()
    except Exception as e:
        return (time.perf_counter() - t) * 1000, f"<<{type(e).__name__}: {str(e)[:70]}>>"


async def main() -> None:
    aclient = AsyncSarvamAI(api_subscription_key=KEY)
    sclient = SarvamAI(api_subscription_key=KEY)
    rows = []

    for label, lang, spoken, ref in CASES:
        print(f"\n{'=' * 78}\n{label}   [{lang}]\n{'=' * 78}")
        print(f"  spoken      : {spoken}")

        ttfb = await tts_stream_ttfb(aclient, spoken, lang)
        wav = tts_batch(sclient, spoken, lang)
        print(f"  TTS         : ttfb {ttfb:.0f}ms (streaming), {len(wav)}B wav (batch)")

        stt_ms, heard = stt(sclient, wav, lang)
        print(f"  STT heard   : {heard}")
        score = wer(ref, heard) if ref else None
        if score is None:
            print(f"  STT         : {stt_ms:.0f}ms  (WER n/a - output script differs from input)")
            _, cm = stt(sclient, wav, lang, mode="codemix")
            print(f"  STT codemix : {cm}")
        else:
            print(f"  STT         : {stt_ms:.0f}ms  WER {score * 100:.0f}%")

        llm_ms, reply = llm(heard if not heard.startswith("<<") else spoken)
        print(f"  agent replies: {reply}")
        print(f"  LLM         : {llm_ms:.0f}ms   (fed the STT transcript)")
        rows.append((label, ttfb, stt_ms, score, llm_ms))

    print(f"\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    print(f"  {'language':22s} {'TTS ttfb':>9s} {'STT':>8s} {'WER':>7s} {'LLM':>8s} {'total':>8s}")
    for label, t_ms, s_ms, score, l_ms in rows:
        w = f"{score * 100:.0f}%" if score is not None else "n/a"
        total = (s_ms or 0) + (l_ms or 0) + (t_ms if t_ms > 0 else 0)
        print(f"  {label:22s} {t_ms:7.0f}ms {s_ms:6.0f}ms {w:>7s} {l_ms:6.0f}ms {total:6.0f}ms")


asyncio.run(main())
