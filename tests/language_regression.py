"""Re-test only the languages that failed before the fixes.

Config is IMPORTED from livekit-agent/agent.py, not hardcoded, so this measures the
deployed behaviour. Old value (hi-IN) is run alongside for a before/after comparison.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(r"c:\Users\RONIT\OneDrive\Desktop\vAPI DEMO 2.1")
sys.path.insert(0, str(ROOT / "livekit-agent"))
os.chdir(ROOT / "livekit-agent")

import agent as AG  # noqa: E402  - pulls in the real prompt + language codes

from sarvamai import SarvamAI  # noqa: E402

KEY = os.environ["SARVAM_API_KEY"]
SPEAKER = AG.TTS_SPEAKER
STT_CODE = AG.STT_LANGUAGE_CODE
TTS_CODE = AG.TTS_LANGUAGE_CODE
PROMPT = AG.SYSTEM_PROMPT
MODEL = AG.LLM_MODEL

print(f"  deployed config: STT={STT_CODE!r}  TTS={TTS_CODE!r}  speaker={SPEAKER!r}")
print(f"  prompt has mirroring rule: {'USI bhasha' in PROMPT}\n")

# Only the ones that were broken before.
BROKEN = [
    ("English",   "en-IN", "I need a truck from Nashik to Pune tomorrow morning for a twenty ton load"),
    ("Punjabi",   "pa-IN", "\u0a2e\u0a48\u0a28\u0a42\u0a70 \u0a15\u0a71\u0a32\u0a4d\u0a39 \u0a38\u0a35\u0a47\u0a30\u0a47 \u0a28\u0a3e\u0a38\u0a3f\u0a15 \u0a24\u0a4b\u0a02 \u0a2a\u0a41\u0a23\u0a47 \u0a32\u0a08 \u0a1f\u0a30\u0a71\u0a15 \u0a1a\u0a3e\u0a39\u0a40\u0a26\u0a3e \u0a39\u0a48"),
    ("Bengali",   "bn-IN", "\u0986\u09ae\u09be\u09b0 \u0995\u09be\u09b2 \u09b8\u0995\u09be\u09b2\u09c7 \u09a8\u09be\u09b8\u09bf\u0995 \u09a5\u09c7\u0995\u09c7 \u09aa\u09c1\u09a8\u09c7 \u09af\u09be\u0993\u09af\u09be\u09b0 \u099c\u09a8\u09cd\u09af \u098f\u0995\u099f\u09bf \u099f\u09cd\u09b0\u09be\u0995 \u09a6\u09b0\u0995\u09be\u09b0"),
    ("Kannada",   "kn-IN", "\u0ca8\u0ca8\u0c97\u0cc6 \u0ca8\u0cbe\u0cb3\u0cc6 \u0cac\u0cc6\u0cb3\u0cbf\u0c97\u0ccd\u0c97\u0cc6 \u0ca8\u0cbe\u0cb8\u0cbf\u0c95\u0ccd\u200c\u0ca8\u0cbf\u0c82\u0ca6 \u0caa\u0cc1\u0ca3\u0cc6\u0c97\u0cc6 \u0c92\u0c82\u0ca6\u0cc1 \u0cb2\u0cbe\u0cb0\u0cbf \u0cac\u0cc7\u0c95\u0cc1"),
    ("Malayalam", "ml-IN", "\u0d0e\u0d28\u0d3f\u0d15\u0d4d\u0d15\u0d4d \u0d28\u0d3e\u0d33\u0d46 \u0d30\u0d3e\u0d35\u0d3f\u0d32\u0d46 \u0d28\u0d3e\u0d38\u0d3f\u0d15\u0d4d\u0d15\u0d3f\u0d7d \u0d28\u0d3f\u0d28\u0d4d\u0d28\u0d4d \u0d2a\u0d42\u0d28\u0d46\u0d2f\u0d3f\u0d32\u0d47\u0d15\u0d4d\u0d15\u0d4d \u0d12\u0d30\u0d41 \u0d32\u0d4b\u0d31\u0d3f \u0d35\u0d47\u0d23\u0d02"),
    ("Odia",      "od-IN", "\u0b2e\u0b4b\u0b24\u0b47 \u0b15\u0b3e\u0b32\u0b3f \u0b38\u0b15\u0b3e\u0b33\u0b47 \u0b28\u0b3e\u0b38\u0b3f\u0b15\u0b30\u0b41 \u0b2a\u0b41\u0b23\u0b47 \u0b2a\u0b30\u0b4d\u0b2f\u0b4d\u0b2f\u0b28\u0b4d\u0b24 \u0b0f\u0b15 \u0b1f\u0b4d\u0b30\u0b15 \u0b26\u0b30\u0b15\u0b3e\u0b30"),
    # reply language was wrong for these two even though STT was fine
    ("Tamil",     "ta-IN", "\u0b8e\u0ba8\u0b95\u0bcd\u0b95\u0bc1 \u0ba8\u0bbe\u0bb3\u0bc8 \u0b95\u0bbe\u0bb2\u0bc8 \u0ba8\u0bbe\u0b9a\u0bbf\u0b95\u0bcd\u0b95\u0bbf\u0bb2\u0bbf\u0bb0\u0bc1\u0ba8\u0bcd\u0ba4\u0bc1 \u0baa\u0bc1\u0ba9\u0bc7\u0bb5\u0bc1\u0b95\u0bcd\u0b95\u0bc1 \u0b92\u0bb0\u0bc1 \u0bb2\u0bbe\u0bb0\u0bbf \u0bb5\u0bc7\u0ba3\u0bcd\u0b9f\u0bc1\u0bae\u0bcd"),
]

URDU = "\u0645\u062c\u06be\u06d2 \u06a9\u0644 \u0635\u0628\u062d \u0646\u0627\u0633\u06a9 \u0633\u06d2 \u067e\u0648\u0646\u06d2 \u06a9\u06d2 \u0644\u06cc\u06d2 \u0679\u0631\u06a9 \u0686\u0627\u06be\u06cc\u06d2"

SCRIPTS = [("Devanagari", 0x0900, 0x097F), ("Bengali", 0x0980, 0x09FF),
           ("Gurmukhi", 0x0A00, 0x0A7F), ("Gujarati", 0x0A80, 0x0AFF),
           ("Odia", 0x0B00, 0x0B7F), ("Tamil", 0x0B80, 0x0BFF),
           ("Telugu", 0x0C00, 0x0C7F), ("Kannada", 0x0C80, 0x0CFF),
           ("Malayalam", 0x0D00, 0x0D7F), ("Arabic", 0x0600, 0x06FF)]


def script_of(s: str) -> str:
    counts: dict[str, int] = {}
    for ch in s:
        o = ord(ch)
        for name, lo, hi in SCRIPTS:
            if lo <= o <= hi:
                counts[name] = counts.get(name, 0) + 1
        if ch.isascii() and ch.isalpha():
            counts["Latin"] = counts.get("Latin", 0) + 1
    return max(counts, key=counts.get) if counts else "?"


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


def llm(text: str) -> str:
    body = json.dumps({"model": MODEL, "max_tokens": 70,
                       "messages": [{"role": "system", "content": PROMPT},
                                    {"role": "user", "content": text}]}).encode()
    req = urllib.request.Request("https://api.sarvam.ai/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return (json.load(r)["choices"][0]["message"]["content"] or "").strip()
    except urllib.error.HTTPError as e:
        return f"<<HTTP {e.code}>>"


c = SarvamAI(api_subscription_key=KEY)
rows = []

for label, native_code, phrase in BROKEN:
    print("=" * 78)
    print(f"{label}")
    print("=" * 78)
    wav = base64.b64decode(c.text_to_speech.convert(
        text=phrase, language_code=native_code, speaker=SPEAKER,
        model="bulbul:v3", speech_sample_rate=16000).audios[0])

    def hear(code):
        f = io.BytesIO(wav)
        f.name = "a.wav"
        try:
            r = c.speech_to_text.transcribe(file=f, model="saaras:v3",
                                            language_code=code, mode="transcribe")
            return (r.transcript or "").strip()
        except Exception as e:
            return f"<<{type(e).__name__}>>"

    old, new = hear("hi-IN"), hear(STT_CODE)
    w_old, w_new = wer(phrase, old) * 100, wer(phrase, new) * 100
    print(f"  OLD (hi-IN)   WER {w_old:3.0f}%  {old[:64]}")
    print(f"  NEW ({STT_CODE}) WER {w_new:3.0f}%  {new[:64]}")

    reply = llm(new)
    rs, ps = script_of(reply), script_of(phrase)
    print(f"  agent reply   [{rs} vs driver {ps}] {'MATCH' if rs == ps else 'MISMATCH'}")
    print(f"    {reply[:110]}")
    print()
    rows.append((label, w_old, w_new, rs == ps, rs, ps))

# Urdu: no way to synthesise Arabic-script audio, so test the two things we CAN.
print("=" * 78)
print("Urdu (input audio not synthesisable - testing the crash paths instead)")
print("=" * 78)
from sarvam_plugins.tts import _is_speakable  # noqa: E402
reply = llm(URDU)
rs = script_of(reply)
print(f"  guard drops Arabic-script chunk : {not _is_speakable(URDU)}")
print(f"  agent replies in               : {rs}  (must NOT be Arabic)")
print(f"    {reply[:110]}")
print(f"  that reply is voiceable        : {_is_speakable(reply)}")

print()
print("=" * 78)
print("SUMMARY")
print("=" * 78)
print(f"  {'language':11s} {'WER old':>8s} {'WER new':>8s}  {'reply lang':>10s}")
for label, wo, wn, match, rs, ps in rows:
    print(f"  {label:11s} {wo:7.0f}% {wn:7.0f}%  {'OK ' + rs if match else 'WRONG ' + rs:>10s}")
