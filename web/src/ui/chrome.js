// Header chrome: call state pill, timer, audio meter, call/mute buttons.

import { STATE_LABEL } from "../constants.js";
import { el } from "../dom.js";
import { store } from "../store.js";

let timerHandle = null;

export function setCallState(next) {
  store.callState = next;
  el["state-pill"].dataset.state = next;
  el["state-label"].textContent = STATE_LABEL[next] || next;
  el["agent-speaking"].classList.toggle("hidden", next !== "speaking");
}

export function updateCallButton() {
  el["call-label"].textContent = store.connected ? "End call" : "Call";
  el["call-toggle"].classList.toggle("active", store.connected);
  el["mute-toggle"].disabled = !store.connected;
  el["mute-toggle"].textContent = store.muted ? "Unmute" : "Mute";
  el["mute-toggle"].classList.toggle("muted", store.muted);
}

export function startTimer() {
  store.startedAt = Date.now();
  clearInterval(timerHandle);
  timerHandle = setInterval(() => {
    const s = Math.floor((Date.now() - store.startedAt) / 1000);
    const pad = (n) => String(n).padStart(2, "0");
    el["call-timer"].textContent = `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
  }, 500);
}

export function stopTimer() {
  clearInterval(timerHandle);
  timerHandle = null;
}

/** Eight bars driven by the agent's live audio level. */
export function setMeter(level) {
  const bars = el.meter.children;
  const lit = Math.round(Math.max(0, Math.min(1, level)) * bars.length);
  for (let i = 0; i < bars.length; i++) bars[i].classList.toggle("on", i < lit);
}
