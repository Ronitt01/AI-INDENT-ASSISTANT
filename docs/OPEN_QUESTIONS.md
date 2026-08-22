# Open questions — updated against Sarvam's public docs (16 Aug 2026)

Status of the roadmap's §6 open questions after checking `docs.sarvam.ai` directly. Two are
now resolved from documentation; the rest genuinely require your account/dashboard/drivers
and can't be resolved from this machine.

## Resolved from docs.sarvam.ai

- **Is Sarvam's chat completions endpoint OpenAI-compatible?** ✅ Yes, confirmed.
  `POST https://api.sarvam.ai/v1/chat/completions` uses the same request/response schema as
  OpenAI's endpoint, and accepts `Authorization: Bearer <key>` in addition to Sarvam's own
  `api-subscription-key` header. This means the LLM leg in Phase 1 is a config line via
  `livekit.plugins.openai.LLM(base_url=...)` — no third adapter needed. See
  [`livekit-agent/agent.py`](../livekit-agent/agent.py).

- **Which model name — "Sarvam-105B", "Sarvam-105B Chat", or "sarvam-105b-conversations"?**
  Partially resolved: the v1 chat completions endpoint documents `sarvam-105b` and
  `sarvam-105b-conversations` as the two available model IDs (both priced identically per
  the roadmap). There's no third "Sarvam-105B Chat" name in the current API reference —
  that was likely the roadmap author's shorthand for one of these two. **Still on you:** run
  your actual indent-taking flow through both during Phase 0 and pick by transcript quality,
  per the roadmap.

## Still open — need your Sarvam account or real driver data

- **How big are your free credits, actually?** Check `dashboard.sarvam.ai` directly — "100
  points" as ₹100 vs $100 is a 100x difference in test budget. Nothing external resolves
  this; it's account-specific.

- **Is Sarvam's inference India-hosted?** The docs don't state a hosting region. Run the
  curl timing test from roadmap §2 yourself, from a network in India:
  ```bash
  curl -o /dev/null -s -w "connect:%{time_connect}s ttfb:%{time_starttransfer}s\n" https://api.sarvam.ai/
  ```
  Compare against the same test against `api.groq.com` or `api.cartesia.ai`.

- **Sarvam-105B's own inference speed (time-to-first-token, tokens/sec).** Not published
  anywhere found. `phase0_prototype/local_prototype.py` prints this number the first time
  you run it against your own API key — that's the only way to get it.

- **Real Hindi/Hinglish accuracy and code-mixing handling.** Needs your drivers' actual
  phrases, not generic test sentences — see `phase0_prototype/test_phrases.py`, which ships
  with a placeholder list you must replace.

- **Which Bulbul voice wins the A/B, and the real character-count-per-minute for TTS cost.**
  Needs a human (ideally whoever picked "Naina" originally) listening to 2-3 `bulbul:v3`
  speakers against your actual driver-facing phrases, run through
  `phase0_prototype/local_prototype.py --voice-ab`.

## One inconsistency worth flagging before you build on it

Sarvam's own docs are not fully consistent between two pages describing the *same*
speech-to-text WebSocket API: the API reference page describes client audio messages as
bare `{"audio": ..., "encoding": ..., "sample_rate": ...}` (no `"type"/"data"` envelope),
while the streaming-tutorial page's SDK example (`ws.transcribe(...)`) sends the same
flat shape but the *server* responses use a `{"type": "data"|"events", "data": {...}}`
envelope. The TTS WebSocket API is internally consistent (`type`/`data` on both directions).
[`livekit-agent/sarvam_plugins/stt.py`](../livekit-agent/sarvam_plugins/stt.py) implements
the flat client-audio-message form as documented, but **verify against a real connection
in Phase 0 before trusting it in production** — a hand-authored client message format from
docs is exactly the kind of detail that's worth 60 seconds of confirmation against a live
socket, per the roadmap's own "sketch, not tested code" caveat.
