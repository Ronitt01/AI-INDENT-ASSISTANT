// Client state. The agent owns the indent; this holds only what the browser
// needs to render it and drive the call.

// Where the token server lives. Baked in at build time from VITE_API_BASE so a
// deployed console talks to a deployed backend; falls back to the local port for
// `npm run dev`. A hardcoded localhost here is invisible in development and fatal
// once deployed - the visitor's browser would dial *their own* machine.
// An operator can still override it per-browser in the settings modal.
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8081";

const DEFAULTS = {
  apiBase: API_BASE,
  userId: "dispatcher-1",
  orderId: "42",
  /** Only one stack now; see src/transport.js. Kept as a key for forward room. */
  voiceStack: "livekit",
};

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem("indentSettings.v2") || "{}");
    // Drop a saved apiBase that points at a machine this browser is not on. Without
    // this, anyone who ever ran the console locally keeps a localhost apiBase in
    // localStorage and the deployed site silently fails for them alone.
    if (saved.apiBase && /localhost|127\.0\.0\.1/.test(saved.apiBase)) {
      if (!/localhost|127\.0\.0\.1/.test(window.location.hostname)) delete saved.apiBase;
    }
    return { ...DEFAULTS, ...saved };
  } catch {
    return { ...DEFAULTS };
  }
}

export const store = {
  room: null,
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
