import { Room, RoomEvent, Track } from "livekit-client";

const statusEl = document.getElementById("status");
const transcriptEl = document.getElementById("transcript");
const connectBtn = document.getElementById("connectBtn");
const micBtn = document.getElementById("micBtn");
const disconnectBtn = document.getElementById("disconnectBtn");

let room = null;

// Browser-side noise handling. Drivers call from truck cabins - engine, wind, horns -
// while every STT accuracy number we measured came from clean synthetic audio, so this
// is the gap that matters most in the field. LiveKit's BVC noise-cancellation plugin is
// NOT an option: its own package metadata says "Requires LiveKit Cloud", and this stack
// is self-hosted. WebRTC's built-in processing is free and runs in the browser.
// voiceIsolation is a stronger noiseSuppression where supported; browsers without it
// ignore the flag and fall back to noiseSuppression.
const MIC_OPTIONS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  voiceIsolation: true,
};

function setStatus(text) {
  statusEl.textContent = text;
}

function appendTranscript(who, text) {
  const p = document.createElement("p");
  p.className = who;
  p.textContent = `${who === "agent" ? "Agent" : "Driver"}: ${text}`;
  transcriptEl.appendChild(p);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

async function connect() {
  const userId = document.getElementById("userId").value.trim();
  const orderId = document.getElementById("orderId").value.trim();
  const tokenServerUrl = document.getElementById("tokenServerUrl").value.trim();

  if (!userId || !orderId || !tokenServerUrl) {
    alert("Fill in driver ID, order ID, and token server URL first.");
    return;
  }

  setStatus("requesting token...");
  const res = await fetch(`${tokenServerUrl}/livekit-token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, order_id: orderId }),
  });
  if (!res.ok) {
    setStatus(`token request failed: ${res.status}`);
    return;
  }
  const { token, url } = await res.json();

  room = new Room();

  room.on(RoomEvent.Connected, () => setStatus("connected"));
  room.on(RoomEvent.Disconnected, () => {
    setStatus("disconnected");
    connectBtn.disabled = false;
    micBtn.disabled = true;
    disconnectBtn.disabled = true;
  });

  room.on(RoomEvent.TrackSubscribed, (track, _publication, participant) => {
    if (track.kind === Track.Kind.Audio) {
      // agent's synthesized voice — attach and play
      const el = track.attach();
      el.dataset.participant = participant.identity;
      document.body.appendChild(el);
    }
  });

  room.on(RoomEvent.TrackUnsubscribed, (track) => {
    track.detach().forEach((el) => el.remove());
  });

  // Live transcript: both the driver's STT output and the agent's spoken text
  // arrive as TranscriptionSegments, distinguished by which participant they're
  // attributed to.
  room.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
    for (const segment of segments) {
      if (!segment.final) continue;
      const isAgent = participant?.identity?.startsWith("agent");
      appendTranscript(isAgent ? "agent" : "driver", segment.text);
    }
  });

  setStatus("connecting...");
  await room.connect(url, token);

  await room.localParticipant.setMicrophoneEnabled(true, MIC_OPTIONS);
  setStatus("connected — mic live");

  connectBtn.disabled = true;
  micBtn.disabled = false;
  disconnectBtn.disabled = false;
}

async function toggleMic() {
  if (!room) return;
  const enabled = room.localParticipant.isMicrophoneEnabled;
  await room.localParticipant.setMicrophoneEnabled(!enabled, MIC_OPTIONS);
  micBtn.textContent = enabled ? "Unmute" : "Mute";
}

async function disconnect() {
  if (!room) return;
  await room.disconnect();
  room = null;
}

connectBtn.addEventListener("click", () => connect().catch((e) => setStatus(`error: ${e.message}`)));
micBtn.addEventListener("click", () => toggleMic().catch((e) => setStatus(`error: ${e.message}`)));
disconnectBtn.addEventListener("click", () => disconnect().catch((e) => setStatus(`error: ${e.message}`)));
