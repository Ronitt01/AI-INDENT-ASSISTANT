// Element lookup and the small formatting helpers every renderer needs.

const IDS = [
  "state-pill", "state-label", "call-timer", "meter", "mute-toggle", "call-toggle",
  "call-label", "settings-btn", "agent-speaking", "messages", "interim",
  "indent-fields", "issues", "completion-card", "progress-text", "ring-fill",
  "copy-json", "metrics-content", "settings-modal", "api-base", "user-id",
  "order-id", "voice-stack", "toast",
];

export const el = Object.fromEntries(IDS.map((id) => [id, document.getElementById(id)]));

export const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Agent timestamps are epoch seconds, not milliseconds. */
export const clock = (ts) => {
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

export function toast(message) {
  el.toast.textContent = message;
  el.toast.classList.add("show");
  setTimeout(() => el.toast.classList.remove("show"), 2400);
}
