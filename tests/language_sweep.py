"""Wider language sweep for the Sarvam legs.

For each language: batch TTS -> STT three ways (native code / auto-detect /
the hi-IN the agent actually ships) -> one LLM turn on the native transcript.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.request

from dotenv import load_dotenv

load_dotenv(r"c:\Users\RONIT\OneDrive\Desktop\vAPI DEMO 2.1\.env")

from sarvamai import SarvamAI

KEY = os.environ["SARVAM_API_KEY"]
SPEAKER = os.environ.get("SARVAM_TTS_SPEAKER", "shubh")
LLM_MODEL = os.environ["SARVAM_LLM_MODEL"]
SYSTEM_PROMPT = (
    "Aap AB Logistics ke liye ek voice assistant hain jo drivers se indent (load booking) "
    "lete hain. Chhote, seedhe jawab dein \u2014 jaise ek dispatcher call par bolta hai, lambi "
    "speeches nahi. Hindi aur Hinglish dono mein baat kar sakte hain, jaisa driver bole."
)

# "I need a truck from Nashik to Pune tomorrow morning" in each language.
CASES = [
    ("Gujarati",  "gu-IN", "\u0aae\u0aa8\u0ac7 \u0a95\u0abe\u0ab2\u0ac7 \u0ab8\u0ab5\u0abe\u0ab0\u0ac7 \u0aa8\u0abe\u0ab6\u0abf\u0a95\u0aa5\u0ac0 \u0aaa\u0ac1\u0aa3\u0ac7 \u0aae\u0abe\u0a9f\u0ac7 \u0a9f\u0acd\u0ab0\u0a95 \u0a9c\u0acb\u0a88\u0a8f \u0a9b\u0ac7"),
    ("Punjabi",   "pa-IN", "\u0a2e\u0a48\u0a28\u0a42\u0a70 \u0a15\u0a71\u0a32\u0a4d\u0a39 \u0a38\u0a35\u0a47\u0a30\u0a47 \u0a28\u0a3e\u0a38\u0a3f\u0a15 \u0a24\u0a4b\u0a02 \u0a2a\u0a41\u0a23\u0a47 \u0a32\u0a08 \u0a1f\u0a30\u0a71\u0a15 \u0a1a\u0a3e\u0a39\u0a40\u0a26\u0a3e \u0a39\u0a48"),
    ("Bengali",   "bn-IN", "\u0986\u09ae\u09be\u09b0 \u0995\u09be\u09b2 \u09b8\u0995\u09be\u09b2\u09c7 \u09a8\u09be\u09b8\u09bf\u0995 \u09a5\u09c7\u0995\u09c7 \u09aa\u09c1\u09a8\u09c7 \u09af\u09be\u0993\u09af\u09be\u09b0 \u099c\u09a8\u09cd\u09af \u098f\u0995\u099f\u09bf \u099f\u09cd\u09b0\u09be\u0995 \u09a6\u09b0\u0995\u09be\u09b0"),
    ("Tamil",     "ta-IN", "\u0b8e\u0ba8\u0b95\u0bcd\u0b95\u0bc1 \u0ba8\u0bbe\u0bb3\u0bc8 \u0b95\u0bbe\u0bb2\u0bc8 \u0ba8\u0bbe\u0b9a\u0bbf\u0b95\u0bcd\u0b95\u0bbf\u0bb2\u0bbf\u0bb0\u0bc1\u0ba8\u0bcd\u0ba4\u0bc1 \u0baa\u0bc1\u0ba9\u0bc7\u0bb5\u0bc1\u0b95\u0bcd\u0b95\u0bc1 \u0b92\u0bb0\u0bc1 \u0bb2\u0bbe\u0bb0\u0bbf \u0bb5\u0bc7\u0ba3\u0bcd\u0b9f\u0bc1\u0bae\u0bcd"),
    ("Telugu",    "te-IN", "\u0c28\u0c3e\u0c15\u0c41 \u0c30\u0c47\u0c2a\u0c41 \u0c09\u0c26\u0c2f\u0c02 \u0c28\u0c3e\u0c38\u0c3f\u0c15\u0c4d \u0c28\u0c41\u0c02\u0c21\u0c3f \u0c2a\u0c42\u0c23\u0c47\u0c15\u0c41 \u0c12\u0c15 \u0c32\u0c3e\u0c30\u0c40 \u0c15\u0c3e\u0c35\u0c3e\u0c32\u0c3f"),
    ("Kannada",   "kn-IN", "\u0ca8\u0ca8\u0c97\u0cc6 \u0ca8\u0cbe\u0cb3\u0cc6 \u0cac\u0cc6\u0cb3\u0cbf\u0c97\u0ccd\u0c97\u0cc6 \u0ca8\u0cbe\u0cb8\u0cbf\u0c95\u0ccd\u200c\u0ca8\u0cbf\u0c82\u0ca6 \u0caa\u0cc1\u0ca3\u0cc6\u0c97\u0cc6 \u0c92\u0c82\u0ca6\u0cc1 \u0cb2\u0cbe\u0cb0\u0cbf \u0cac\u0cc7\u0c95\u0cc1"),
    ("Malayalam", "ml-IN", "\u0d0e\u0d28\u0d3f\u0d15\u0d4d\u0d15\u0d4d \u0d28\u0d3e\u0d33\u0d46 \u0d30\u0d3e\u0d35\u0d3f\u0d32\u0d46 \u0d28\u0d3e\u0d38\u0d3f\u0d15\u0d4d\u0d15\u0d3f\u0d7d \u0d28\u0d3f\u0d28\u0d4d\u0d28\u0d4d \u0d2a\u0d42\u0d28\u0d46\u0d2f\u0d3f\u0d32\u0d47\u0d15\u0d4d\u0d15\u0d4d \u0d12\u0d30\u0d41 \u0d32\u0d4b\u0d31\u0d3f \u0d35\u0d47\u0d23\u0d02"),
    ("Odia",      "od-IN", "\u0b2e\u0b4b\u0b24\u0b47 \u0b15\u0b3e\u0b32\u0b3f \u0b38\u0b15\u0b3e\u0b33\u0b47 \u0b28\u0b3e\u0b38\u0b3f\u0b15\u0b30\u0b41 \u0b2a\u0b41\u0b23\u0b47 \u0b2a\u0b30\u0b4d\u0b2f\u0b4d\u0b2f\u0b28\u0b4d\u0b24 \u0b0f\u0b15 \u0b1f\u0b4d\u0b30\u0b15 \u0b26\u0b30\u0b15\u0b3e\u0b30"),
    ("Urdu",      "ur-IN", "\u0645\u062c\u06be\u06d2 \u06a9\u0644 \u0635\u0628\u062d \u0646\u0627\u0633\u06a9 \u0633\u06d2 \u067e\u0648\u0646\u06d2 \u06a9\u06d2 \u0644\u06cc\u06d2 \u0679\u0631\u06a9 \u0686\u0627\u06be\u06cc\u06d2"),
]


def words(s):
    return re.sub(r"[^\w\s]", " ", s.lower()).split()


def wer(ref, hyp):
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


def llm(text):
    body = json.dumps({"model": LLM_MODEL, "max_tokens": 70,
                       "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": text}]}).encode()
    req = urllib.request.Request("https://api.sarvam.ai/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return (json.load(r)["choices"][0]["message"]["content"] or "").strip()
    except urllib.error.HTTPError as e:
        return f"<<HTTP {e.code}>>"


def script_of(s):
    """Crude script detector, enough to tell 'replied in my language' from 'replied in Hindi'."""
    ranges = [("Devanagari", 0x0900, 0x097F), ("Bengali", 0x0980, 0x09FF),
              ("Gurmukhi", 0x0A00, 0x0A7F), ("Gujarati", 0x0A80, 0x0AFF),
              ("Odia", 0x0B00, 0x0B7F), ("Tamil", 0x0B80, 0x0BFF),
              ("Telugu", 0x0C00, 0x0C7F), ("Kannada", 0x0C80, 0x0CFF),
              ("Malayalam", 0x0D00, 0x0D7F), ("Arabic", 0x0600, 0x06FF)]
    counts = {}
    for ch in s:
        o = ord(ch)
        for name, lo, hi in ranges:
            if lo <= o <= hi:
                counts[name] = counts.get(name, 0) + 1
        if ch.isascii() and ch.isalpha():
            counts["Latin"] = counts.get("Latin", 0) + 1
    return max(counts, key=counts.get) if counts else "?"


def main():
    c = SarvamAI(api_subscription_key=KEY)
    rows = []
    for label, lang, phrase in CASES:
        print(f"\n{'=' * 78}\n{label}  [{lang}]\n{'=' * 78}")
        print(f"  spoken        : {phrase}")
        try:
            t = time.perf_counter()
            wav = base64.b64decode(c.text_to_speech.convert(
                text=phrase, language_code=lang, speaker=SPEAKER,
                model="bulbul:v3", speech_sample_rate=16000).audios[0])
            tts_ms = (time.perf_counter() - t) * 1000
        except Exception as e:
            print(f"  TTS           : FAILED {type(e).__name__}: {str(e)[:90]}")
            rows.append((label, None, None, None, None, "TTS failed"))
            continue
        print(f"  TTS           : {len(wav)}B in {tts_ms:.0f}ms")

        def hear(code):
            f = io.BytesIO(wav)
            f.name = "a.wav"
            try:
                r = c.speech_to_text.transcribe(file=f, model="saaras:v3",
                                                language_code=code, mode="transcribe")
                return (r.transcript or "").strip()
            except Exception as e:
                return f"<<{type(e).__name__}>>"

        native, auto, hindi = hear(lang), hear("unknown"), hear("hi-IN")
        w_native = wer(phrase, native) * 100
        w_auto = wer(phrase, auto) * 100
        w_hindi = wer(phrase, hindi) * 100
        print(f"  STT native    : {native}")
        print(f"                  WER {w_native:.0f}%")
        print(f"  STT auto      : {auto[:80]}")
        print(f"                  WER {w_auto:.0f}%")
        print(f"  STT as hi-IN  : {hindi[:80]}")
        print(f"                  WER {w_hindi:.0f}%  <- your deployed config")

        reply = llm(native)
        print(f"  agent replies : {reply[:100]}")
        print(f"  reply script  : {script_of(reply)}  (driver spoke {script_of(phrase)})")
        rows.append((label, w_native, w_auto, w_hindi, script_of(reply), script_of(phrase)))

    print(f"\n{'=' * 78}\nSUMMARY - WER by STT language_code (lower is better)\n{'=' * 78}")
    print(f"  {'language':12s} {'native':>8s} {'auto':>8s} {'hi-IN':>8s}   {'agent replied in':<16s} {'driver used'}")
    for label, wn, wa, wh, rs, ps in rows:
        if wn is None:
            print(f"  {label:12s} {'-':>8s} {'-':>8s} {'-':>8s}   {rs}")
            continue
        print(f"  {label:12s} {wn:7.0f}% {wa:7.0f}% {wh:7.0f}%   {rs:<16s} {ps}")


main()
