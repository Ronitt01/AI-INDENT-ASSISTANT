# AB Logistics Indent Assistant — self-hosted voice AI

Replaces Vapi with a self-hosted WebRTC voice pipeline (LiveKit + Sarvam AI) for the web app
and Android app. No telephony, no SIP, no phone number.

Built from `voiceaiselfhostroadmap.md` (v2, 16 Aug 2026). See that file for the cost/latency
analysis this implementation is based on.

## Layout

| Path | What it is |
|---|---|
| [`web/`](web) | **Operator console** — the UI you actually use. Live conversation, the 8-field indent panel with confidence/provenance, editable fields, call metrics. Renders state the agent publishes; holds no secrets. |
| [`web/simple.html`](web/simple.html) | Bare-bones client kept for debugging the transport without the console's machinery. |
| [`livekit-agent/agent.py`](livekit-agent/agent.py) | The agent worker: Sarvam STT → LLM → TTS per call, plus the `upsert_indent` / `confirm_indent` tools that fill the indent. |
| [`livekit-agent/indent/`](livekit-agent/indent) | Indent capture domain — fields, confidence ladder, extraction lexicon, validation. Pure Python, no LiveKit, unit-testable without a room. |
| [`livekit-agent/indent_channel.py`](livekit-agent/indent_channel.py) | The data channel: agent publishes state on `indent-state`, operator edits arrive on `operator-edit`. |
| [`livekit-agent/indent_prompts.py`](livekit-agent/indent_prompts.py) | The system prompt. Highest-leverage file here; kept separate so tuning it is a readable diff. |
| [`livekit-agent/sarvam_plugins/`](livekit-agent/sarvam_plugins) | Custom LiveKit STT/TTS adapters for Sarvam (Saaras + Bulbul). |
| [`livekit-agent/call_logging.py`](livekit-agent/call_logging.py) | Transcript/cost/latency/error logging to SQLite. |
| [`backend/`](backend) | Token endpoint (FastAPI). Also creates the agent dispatch — see its module docstring for why that is required. |
| [`android/`](android) | Minimal LiveKit Android client (Kotlin) to merge into the existing app. |
| [`phase0_prototype/`](phase0_prototype) | Standalone script hitting Sarvam directly — no LiveKit. Useful for voice A/B and latency spot-checks. |
| [`tests/`](tests) | Language matrix, sweep, and regression scripts. Hit the live APIs, so they cost credits. |
| [`docs/`](docs) | Rollout plan and the open questions that need your account or your drivers. |

## Running the whole thing locally

Four processes. Ports matter: the token server's CORS allow-list and the console's
default `apiBase` must agree, or "Call" fails with a CORS error three layers from
the cause.

```bash
# 1. LiveKit dev server (advertises 127.0.0.1 for ICE - see docker-compose.yml)
cd livekit-agent && docker compose up -d

# 2. Token server. 8081 rather than 8080 because 8080 is often already taken;
#    ALLOWED_ORIGINS must list the console's origin.
cd backend && ALLOWED_ORIGINS=http://localhost:5180   ../.venv/Scripts/python -m uvicorn token_server:app --port 8081

# 3. Agent worker (first run: `python agent.py download-files` for turn-detector weights)
cd livekit-agent && ../.venv/Scripts/python agent.py dev

# 4. Operator console
npm run dev --prefix web -- --port 5180 --strictPort --host 0.0.0.0
```

Then open http://localhost:5180, press **Call**, allow the mic.

## Before you run anything

You need, none of which this repo can supply:

1. A **Sarvam AI API key** (`SARVAM_API_KEY`) — https://dashboard.sarvam.ai
2. A **LiveKit** deployment — either `docker compose up` in `livekit-agent/` for local dev,
   or a LiveKit Cloud project (`LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`)
3. Real Hindi/Hinglish test phrases from your drivers (see `phase0_prototype/test_phrases.py`
   for the placeholder list — replace it before trusting any latency/accuracy number)

Copy `.env.example` to `.env` in each of `phase0_prototype/`, `livekit-agent/`, and `backend/`
and fill in your own keys. **Never commit `.env`.**

## Order of operations

```bash
# Phase 0 — prove the pipeline, get real latency numbers, pick a voice
cd phase0_prototype && pip install -r requirements.txt && python local_prototype.py

# Phase 1b — local LiveKit server + agent
cd livekit-agent && docker compose up -d && pip install -r requirements.txt
python agent.py dev

# Phase 2 — token backend
cd backend && pip install -r requirements.txt && uvicorn token_server:app --reload --port 8080

# Phase 3 — web client
cd web && npm install && npm run dev
```

Then open the web client, allow mic access, and talk to the agent. Android integration
(`android/`) mirrors the same LiveKit connect/token flow — see its README for merging into
the existing app.

## Languages

Measured against the live Sarvam APIs (Aug 2026), 12 languages, TTS->STT round-trip:

- **STT (`SARVAM_STT_LANGUAGE_CODE`, default `unknown`)** — `unknown` means auto-detect.
  It scored 0-6% WER on Hindi, Marathi, Gujarati, Punjabi, Bengali, Tamil, Telugu,
  Kannada, Malayalam, Odia and English, matching a correctly-named language code in every
  case. A hardcoded `hi-IN` instead mangles English, Punjabi (80% WER), Bengali (92%),
  Kannada (67%), Malayalam (59%) and Odia (90%) — so leave this on `unknown` unless you
  have a reason not to.
- **TTS (`SARVAM_TTS_LANGUAGE_CODE`, default `hi-IN`)** — must name a real language;
  Bulbul rejects `unknown`. This does not restrict output language: Bulbul is
  script-driven, and `hi-IN` voiced Telugu text at 0% round-trip WER.
- **Urdu is not supported for output.** `bulbul:v3` rejects Arabic script under every
  language code, so the system prompt tells the agent to answer Urdu speakers in
  Devanagari Hindi, and the TTS adapter drops unvoiceable chunks rather than failing
  the call.

Reply language is pinned by the system prompt (mirror the driver). Before that
instruction existed, a Tamil driver got Hindi back and a Bengali driver got Hinglish.

## Changing the voice

The Bulbul speaker is one line in `.env` — nothing else needs editing:

```
SARVAM_TTS_SPEAKER=anushka
```

Read by the prototype (`local_prototype.py`), the LiveKit agent (`agent.py`), and the
TTS plugin default (`sarvam_plugins/tts.py`), so all three stay in sync. An explicit
`speaker=` argument to `TTSOptions` still overrides it. Restart the agent to pick up a
change; there is no hot-reload.

`--voice-ab` ignores this deliberately — it sweeps `CANDIDATE_SPEAKERS` in
`phase0_prototype/test_phrases.py`, which is the list you A/B *to decide* what to put in
`.env`. `SARVAM_LANGUAGE_CODE` and `SARVAM_LLM_MODEL` work the same way.

## What's NOT done for you (and can't be, from here)

- **Phase 0 validation itself** — the actual latency numbers, the Hindi/Hinglish accuracy
  check, the voice A/B, and the real Sarvam TTS character-count sample all require your
  API key, your drivers' phrases, and a human listening to the A/B. The script is ready;
  running it and judging the output is not something that can be done without your Sarvam
  account. See `docs/OPEN_QUESTIONS.md`.
- **Phase 6 soak time** — routing a % of real traffic to the new stack and comparing
  against Vapi for 1-2 weeks is calendar time on your production traffic, not code.
  `docs/ROLLOUT.md` gives you the plan and the traffic-split config; running it is on you.
- Merging the Android reference client into your existing Vapi-based Android app — this repo
  gives you a minimal standalone module, not a patch against your actual app's source.
