// Call lifecycle: joining the room, playing the agent's audio, and receiving the
// indent state it publishes.
//
// The browser holds no vendor secrets — it asks the backend for a short-lived
// room token at call time.

import { Room, RoomEvent, Track } from "livekit-client";

// Drivers call from truck cabins - engine, wind, horns - and every STT accuracy
// number we measured came from clean synthetic audio, so this is the widest gap
// between the test bench and the field. LiveKit's BVC plugin is not an option: its
// package metadata says "Requires LiveKit Cloud" and this stack is self-hosted.
// voiceIsolation is a stronger noiseSuppression where the browser supports it.
const MIC_OPTIONS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  voiceIsolation: true,
};

import { EDIT_TOPIC, STATE_TOPIC } from "../constants.js";
import { toast } from "../dom.js";
import { store } from "../store.js";
import { requestToken } from "../api.js";

/**
 * @param {object} handlers
 * @param {(snapshot: object) => void} handlers.onSnapshot
 * @param {(text: string) => void}     handlers.onInterim
 * @param {(state: string) => void}    handlers.onCallState
 * @param {(level: number) => void}    handlers.onAudioLevel
 * @param {() => void}                 handlers.onConnected
 * @param {() => void}                 handlers.onDisconnected
 */
export async function connect(handlers) {
  handlers.onCallState("connecting");

  let token;
  let url;
  try {
    ({ token, url } = await requestToken());
  } catch (err) {
    console.error(err);
    handlers.onCallState("idle");
    toast(err.message.slice(0, 140));
    return;
  }

  const room = new Room();
  store.room = room;

  room.on(RoomEvent.Connected, () => {
    store.connected = true;
    handlers.onConnected();
  });

  room.on(RoomEvent.Disconnected, () => {
    store.connected = false;
    store.muted = false;
    handlers.onDisconnected();
  });

  room.on(RoomEvent.TrackSubscribed, (track) => {
    if (track.kind === Track.Kind.Audio) document.body.appendChild(track.attach());
  });
  room.on(RoomEvent.TrackUnsubscribed, (track) => {
    track.detach().forEach((element) => element.remove());
  });

  // The agent is the source of truth for indent state; the console only renders it.
  room.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
    if (topic !== STATE_TOPIC) return;
    try {
      handlers.onSnapshot(JSON.parse(new TextDecoder().decode(payload)));
    } catch (err) {
      console.error("bad state payload", err);
    }
  });

  room.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
    if (participant?.identity?.startsWith("agent")) return;
    handlers.onInterim(segments.filter((s) => !s.final).map((s) => s.text).join(" "));
  });

  room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
    const agentSpeaking = speakers.some((s) => s.identity?.startsWith("agent"));
    if (store.connected) handlers.onCallState(agentSpeaking ? "speaking" : "listening");
    handlers.onAudioLevel(agentSpeaking ? (speakers[0]?.audioLevel ?? 0.5) : 0);
  });

  try {
    await room.connect(url, token);
    await room.localParticipant.setMicrophoneEnabled(true, MIC_OPTIONS);
  } catch (err) {
    console.error(err);
    handlers.onCallState("idle");
    toast(`Connection failed: ${err.message}`.slice(0, 140));
  }
}

export async function disconnect() {
  if (store.room) await store.room.disconnect();
  store.room = null;
}

export async function setMuted(muted) {
  if (!store.room) return;
  store.muted = muted;
  await store.room.localParticipant.setMicrophoneEnabled(!muted, MIC_OPTIONS);
}

/** Send an operator correction; empty value clears the field. */
export function sendEdit(field, value) {
  if (!store.room?.localParticipant) return false;
  try {
    store.room.localParticipant.publishData(
      new TextEncoder().encode(JSON.stringify({ field, value })),
      { topic: EDIT_TOPIC, reliable: true }
    );
    return true;
  } catch (err) {
    console.error(err);
    return false;
  }
}
