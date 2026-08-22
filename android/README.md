# Phase 4 — Android integration reference

This is **not** a standalone runnable Gradle project — there's no existing Android
app in this repo to attach one to, and you already have a Vapi-based Android app
that this needs to merge into (per the roadmap: "Same shape as the Vapi Android
integration you already scoped — swap the SDK"). What's here is the minimal set of
changes to make in your existing app, confirmed against the current
[client-sdk-android](https://github.com/livekit/client-sdk-android) README (v2.28).

## 1. Dependencies — add to your app module's `build.gradle`

See [`build.gradle.kts.snippet`](build.gradle.kts.snippet). You also need JitPack in
`settings.gradle` — see the snippet's header comment.

## 2. Permissions — add to `AndroidManifest.xml`

See [`AndroidManifest.xml.snippet`](AndroidManifest.xml.snippet). `RECORD_AUDIO` is
required; the foreground-service permission is only needed if a call should survive
the app backgrounding (the roadmap flags this as "the same foreground-service
consideration" you'd have hit with Vapi).

## 3. Connect flow — see `VoiceCallActivity.kt`

[`VoiceCallActivity.kt`](VoiceCallActivity.kt) is a complete, minimal
`AppCompatActivity` covering: requesting `RECORD_AUDIO` at runtime, fetching a token
from [`backend/token_server.py`](../backend/token_server.py) (via a plain
`HttpURLConnection` call — no extra HTTP library assumed), connecting to the room,
publishing the mic, and listening for `RoomEvent.TrackSubscribed` /
`TranscriptionReceived` to know the agent is talking and see the live transcript.
Subscribed audio tracks play automatically — no manual audio routing needed.

**To merge**: don't drop this file into your app verbatim. Pull the LiveKit-specific
parts (`connectToRoom()`, the event-handling `when` block, the token fetch) into
wherever your existing Vapi call screen currently lives, and delete the Vapi SDK
calls it replaces. The package name (`com.ablogistics.indentassistant.voice`) is a
placeholder — rename it to match your app.

## What this doesn't cover

- UI/UX polish — this is the wiring, not a call-screen design.
- Your app's existing auth — `userId`/`orderId` here are hardcoded stand-ins for
  whatever your app already knows about the logged-in driver and their current load.
- Foreground service implementation, if you decide you need one for backgrounding —
  only the manifest permission is stubbed in.
