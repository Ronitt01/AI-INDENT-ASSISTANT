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

## Deploying

The console and the token endpoint both deploy to Vercel. The other two components
cannot, and it is worth being clear why:

| Component | Where it runs | Why |
|---|---|---|
| `web/` console | **Vercel** static build | — |
| `api/livekit-token.py` | **Vercel** Python function | same origin as the console, so no CORS at all |
| LiveKit media server | **LiveKit Cloud** (free tier is enough to start) | WebRTC media, not HTTP. The local `docker compose` server is for development only |
| `livekit-agent/` worker | anywhere with outbound internet — your machine, or a container host | a persistent process that joins rooms and holds sockets for the length of a call |

The worker is the part people expect to be hardest to place, and it is not: it dials
*out* to LiveKit and waits for jobs, so it needs no inbound port and no public
address. Running it on a laptop against LiveKit Cloud is a legitimate demo setup.

### 1. LiveKit Cloud

Create a project and copy the three values. They replace the `devkey`/`secret` pair
that only exists for local development.

### 2. Vercel

Import the repo. [`vercel.json`](vercel.json) already supplies the build command,
output directory, SPA rewrite (which deliberately excludes `/api`) and a
`microphone=(self)` permissions policy. Set these environment variables:

```
LIVEKIT_URL           wss://<project>.livekit.cloud
LIVEKIT_API_KEY       <from LiveKit Cloud>
LIVEKIT_API_SECRET    <from LiveKit Cloud>
LIVEKIT_AGENT_NAME    indent-assistant          # optional
TOKEN_TTL_MINUTES     15                        # optional
TOKEN_SHARED_SECRET   <a long random string>    # optional, see below
```

`VITE_API_BASE` is deliberately **not** required. With it unset the console resolves
its backend at runtime: `http://localhost:8081` when served from localhost, and
`/api` otherwise. Set it only to point a deployed console at a token server hosted
somewhere other than Vercel.

### 3. The agent worker

Point it at the same LiveKit Cloud project and run it:

```bash
cd livekit-agent
LIVEKIT_URL=wss://<project>.livekit.cloud LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... ../.venv/Scripts/python agent.py dev      # `start` for a long-running deployment
```

Without a worker registered, a caller connects to a room and hears nothing: the
token endpoint creates the dispatch, but there is nobody to accept it.

### Before a public URL points at this

- **Authentication.** The token endpoint mints a join token for any `order_id` it is
  given. `TOKEN_SHARED_SECRET` adds a single shared header check — enough to stop a
  drive-by, not enough for production, because every caller holds the same string.
  Wire it to your app's session before real drivers use it.
- **Token lifetime** defaults to 15 minutes rather than the SDK's several hours. A
  leaked token is only interesting while it is valid.
- **`ALLOWED_ORIGINS`** only matters for the local FastAPI server. The Vercel function
  is same-origin and needs no allow-list — which is the main reason it exists.

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

## Changing the LLM

By default the LLM leg is Sarvam's own `sarvam-105b-conversations`, in the same region
as STT and TTS. Two `.env` switches move it elsewhere, and `agent.py::_build_llm()`
checks them in this order:

```
USE_OPENROUTER=true
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=stealth/ox-alpha
```

```
USE_GROQ_FALLBACK=true
GROQ_API_KEY=...
```

Both leave India for the LLM round trip while STT/TTS stay on Sarvam, so they cost
latency — the agent logs a warning at startup and the per-call metrics show the LLM
TTFT. Check that number before keeping either.

Whatever you pick **must support tool calling**: the indent is filled by the model
calling `upsert_indent`, so a model without tools produces an empty indent no matter how
well it talks. `OPENROUTER_SITE_URL` / `OPENROUTER_APP_NAME` are optional and only set
OpenRouter's `HTTP-Referer` / `X-Title` leaderboard headers. Restart the agent to pick
up a change.

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
