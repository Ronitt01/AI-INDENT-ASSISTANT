// Client state. The agent owns the indent; this holds only what the browser
// needs to render it and drive the call.

// Where the token server lives. Resolved at RUNTIME, not just build time, because a
// single build has to work in two places:
//
//   served from localhost -> the FastAPI token server on :8081
//   served from anywhere  -> /api/livekit-token, the Vercel function, same origin
//
// Same origin is the point: it removes CORS from the deployment entirely, rather
// than maintaining an allow-list of every host the console might be served from.
// VITE_API_BASE overrides both, for pointing a deployed console at a token server
// hosted somewhere other than Vercel.
function resolveApiBase() {
  if (import.meta.env.VITE_API_BASE) return import.meta.env.VITE_API_BASE;
  const local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname);
  return local ? "http://localhost:8081" : "/api";
}

const API_BASE = resolveApiBase();

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
    const savedIsLocal = /localhost|127\.0\.0\.1/.test(saved.apiBase || "");
    const pageIsLocal = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname);
    if (savedIsLocal && !pageIsLocal) delete saved.apiBase;
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
