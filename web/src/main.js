// Operator console entrypoint: wires events to renderers.
//
// The agent owns the indent. This page renders the state the agent publishes and
// sends operator corrections back; it performs no extraction of its own. That is
// the point of the migration — the model already understood the call, so the
// console displays that understanding instead of reconstructing it.

import { copyIndent } from "./api.js";
import { el, toast } from "./dom.js";
import { connect, disconnect, sendEdit, setMuted } from "./transport.js";
import { renderMessages, setInterim } from "./render/conversation.js";
import { beginEdit, renderIndent, resetIndentRenderState } from "./render/indent.js";
import { renderMetrics } from "./render/metrics.js";
import { store } from "./store.js";
import {
  setCallState,
  setMeter,
  startTimer,
  stopTimer,
  updateCallButton,
} from "./ui/chrome.js";
import { closeSettings, commitSettings, openSettings } from "./ui/settings.js";

function renderAll() {
  renderIndent();
  renderMessages();
  renderMetrics();
}

// --- call control ---------------------------------------------------------

const handlers = {
  onSnapshot: (snapshot) => {
    store.snapshot = snapshot;
    renderAll();
  },
  onInterim: setInterim,
  onCallState: setCallState,
  onAudioLevel: setMeter,
  onConnected: () => {
    updateCallButton();
    setCallState("listening");
    startTimer();
  },
  onDisconnected: () => {
    updateCallButton();
    setCallState("idle");
    stopTimer();
    setMeter(0);
  },
};

function toggleCall() {
  if (store.connected || store.callState === "connecting") {
    disconnect();
  } else {
    resetIndentRenderState();
    connect(handlers);
  }
}

async function toggleMute() {
  await setMuted(!store.muted);
  updateCallButton();
}

// --- operator edits -------------------------------------------------------

function commitEdit(field, value) {
  // A null field means the edit was cancelled — just re-render.
  if (field !== null) {
    toast(sendEdit(field, value) ? "Correction sent to the agent." : "Couldn't send the correction.");
  }
  renderIndent();
}

el["indent-fields"].addEventListener("click", (e) => {
  const why = e.target.closest(".why-btn");
  if (why) {
    const key = why.dataset.why;
    store.expanded.has(key) ? store.expanded.delete(key) : store.expanded.add(key);
    renderIndent();
    return;
  }
  const value = e.target.closest(".field-value");
  if (value) beginEdit(value, commitEdit);
});

el["indent-fields"].addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const value = e.target.closest(".field-value");
  if (value) {
    e.preventDefault();
    beginEdit(value, commitEdit);
  }
});

// --- wiring ---------------------------------------------------------------

el["call-toggle"].addEventListener("click", toggleCall);
el["mute-toggle"].addEventListener("click", toggleMute);
el["settings-btn"].addEventListener("click", openSettings);
el["copy-json"].addEventListener("click", copyIndent);
document.getElementById("settings-save").addEventListener("click", commitSettings);
document.getElementById("settings-close").addEventListener("click", closeSettings);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeSettings();
});

/**
 * Render a snapshot without a live call.
 *
 * Not test scaffolding: this is how you iterate on the console, reproduce a
 * reported rendering bug, or demo the UI without spending call minutes. Feed it
 * the snapshot the agent logs at the end of a call, or `fixtures/`.
 */
window.applySnapshot = (snapshot) => {
  store.snapshot = snapshot;
  renderAll();
};

renderAll();
updateCallButton();
setCallState("idle");
