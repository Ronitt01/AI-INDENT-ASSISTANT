// Talking to the backend.

import { el, toast } from "./dom.js";
import { store } from "./store.js";

export function indentJson() {
  return JSON.stringify(store.snapshot?.plain ?? {}, null, 2);
}

export async function requestToken() {
  const { apiBase, userId, orderId } = store.settings;
  const res = await fetch(`${apiBase}/livekit-token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, order_id: orderId }),
  });
  if (!res.ok) {
    throw new Error(`token request failed (${res.status}): ${await res.text()}`);
  }
  return res.json();
}

export function downloadIndent() {
  const blob = new Blob([indentJson()], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "indent.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function submitIndent() {
  const snap = store.snapshot;
  if (!snap) return;
  const note = document.getElementById("submit-note");
  note.textContent = "Submitting…";

  try {
    const res = await fetch(`${store.settings.apiBase}/indents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        call_id: snap.callId,
        order_id: store.settings.orderId,
        user_id: store.settings.userId,
        plain: snap.plain,
        fields: snap.indent.fields,
        issues: snap.issues,
        metrics: snap.metrics,
        transcript: snap.transcript,
        confirmed: snap.indent.confirmed,
      }),
    });
    const body = await res.json().catch(() => ({}));
    // Report what actually came back rather than assuming success.
    note.textContent = res.ok
      ? `Saved as indent #${body.indent_id}.`
      : `Server replied ${res.status}.`;
    toast(res.ok ? "Indent saved." : `Save failed (${res.status})`);
  } catch (err) {
    note.textContent = `Request failed: ${err.message}`;
    toast("Save failed.");
  }
}

export async function copyIndent() {
  try {
    await navigator.clipboard.writeText(indentJson());
    toast("Indent copied as JSON.");
  } catch {
    console.log(indentJson());
    toast("Clipboard blocked — see console.");
  }
}
