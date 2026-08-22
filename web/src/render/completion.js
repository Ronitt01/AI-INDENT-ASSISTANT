// The completion card: what the operator acts on once all eight fields are in.
//
// Gated on the agent's own `canConfirm`, so a blocking validation error (delivery
// before pickup) disables submission rather than being buried in a warning list.

import { ALL_FIELDS } from "../constants.js";
import { el, esc } from "../dom.js";
import { store } from "../store.js";
import { downloadIndent, submitIndent } from "../api.js";

export function renderCompletion() {
  const snap = store.snapshot;
  const card = el["completion-card"];
  if (!snap?.indent?.complete) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");

  const blocked = !snap.canConfirm;
  card.innerHTML = `
    <div class="completion-head ${blocked ? "blocked" : ""}">
      <span class="completion-tick">${blocked ? "!" : "&#10003;"}</span>
      <span>${blocked ? "All fields captured — needs attention" : "Ready to submit"}</span>
    </div>
    <div class="completion-summary">
      ${ALL_FIELDS.map(([key, label]) => `
        <div class="summary-row">
          <span class="summary-key">${label}</span>
          <span class="summary-val">${esc(snap.plain[key] ?? "—")}</span>
        </div>`).join("")}
    </div>
    ${blocked ? `<p class="completion-note">${snap.blockedBy.map(esc).join("<br>")}</p>` : ""}
    <div class="completion-actions">
      <button id="submit-indent" class="primary-btn" ${blocked ? "disabled" : ""}>Submit indent</button>
      <button id="download-json" class="ghost-btn">Download</button>
    </div>
    <p class="completion-note" id="submit-note">${
      snap.indent.confirmed
        ? "The caller confirmed the full summary on the call."
        : "The caller has not yet confirmed the full summary — individual fields may still be confirmed."
    }</p>`;

  document.getElementById("submit-indent")?.addEventListener("click", submitIndent);
  document.getElementById("download-json").addEventListener("click", downloadIndent);
}
