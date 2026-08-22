// Client state. The agent owns the indent; this holds only what the browser
// needs to render it and drive the call.

const DEFAULTS = {
  apiBase: "http://localhost:8081",
  userId: "dispatcher-1",
  orderId: "42",
  /** "livekit" (LiveKit + Sarvam) or "vapi". See src/transport.js. */
  voiceStack: "livekit",
  /** The Vapi bridge service — only used when voiceStack is "vapi". */
  vapiBase: "http://localhost:8090",
};

function loadSettings() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("indentSettings.v2") || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}

export const store = {
  room: null,
  /** Vapi client and its state socket; null on the LiveKit stack. */
  vapi: null,
  stateSocket: null,
  /** Transport module pinned for the duration of the current call. */
  activeStack: null,
  connected: false,
  muted: false,
  callState: "idle",
  /** Latest snapshot published by the agent. */
  snapshot: null,
  /** Field keys whose provenance panel is open. */
  expanded: new Set(),
  startedAt: null,
  settings: loadSettings(),
};

export function saveSettings(settings) {
  store.settings = settings;
  localStorage.setItem("indentSettings.v2", JSON.stringify(settings));
}
