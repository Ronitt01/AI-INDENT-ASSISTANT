// The indent panel: eight field cards, grouped, each explaining itself on demand.

import { ALL_FIELDS, CONF_EXPLAIN, CONF_LABEL, FIELD_GROUPS, SOURCE_LABEL } from "../constants.js";
import { clock, el, esc } from "../dom.js";
import { store } from "../store.js";
import { renderCompletion } from "./completion.js";

// Tracked so a field that fills mid-call can flash once, rather than every render.
let previousFilled = new Set();

export function renderIndent(onEdit) {
  const fields = store.snapshot?.indent?.fields || {};
  const filledNow = new Set(Object.keys(fields));
  const justFilled = [...filledNow].filter((k) => !previousFilled.has(k));
  previousFilled = filledNow;

  el["indent-fields"].innerHTML = FIELD_GROUPS.map((group) => `
    <div class="field-group">
      <div class="group-title">${group.title}</div>
      ${group.fields
        .map(([key, label]) => card(key, label, fields[key], justFilled.includes(key)))
        .join("")}
    </div>`).join("");

  renderProgress(filledNow.size);
  renderIssues();
  renderCompletion(onEdit);
}

function renderProgress(count) {
  el["progress-text"].textContent = `${count}/${ALL_FIELDS.length}`;
  const circumference = 2 * Math.PI * 15.5;
  el["ring-fill"].style.strokeDasharray = `${circumference}`;
  el["ring-fill"].style.strokeDashoffset =
    `${circumference * (1 - count / ALL_FIELDS.length)}`;
  el["ring-fill"].classList.toggle("complete", count === ALL_FIELDS.length);
}

function card(key, label, slot, flash) {
  const filled = !!slot?.value;
  const changes = slot?.history?.length || 0;
  const open = store.expanded.has(key);
  const warned = filled && slot.warnings?.length;

  const classes = [
    "field-card",
    filled && "confirmed",
    flash && "flash",
    open && "open",
    warned && "warned",
  ].filter(Boolean).join(" ");

  return `
    <div class="${classes}" data-key="${key}">
      <div class="field-row">
        <span class="field-label">${label}</span>
        <span class="field-meta">
          ${changes ? `<span class="chip-changed" title="Changed ${changes} time(s)">${changes + 1}&times;</span>` : ""}
          ${warned ? `<span class="chip-warn" title="${esc(slot.warnings.join(" · "))}">!</span>` : ""}
          <span class="field-status">${filled ? (CONF_LABEL[slot.confidence] || "heard") : "waiting"}</span>
          ${filled ? `<button class="why-btn" data-why="${key}" aria-expanded="${open}" aria-label="Why this value?">i</button>` : ""}
        </span>
      </div>
      <div class="field-value" data-key="${key}" tabindex="0" role="button"
           title="Click to correct">${filled ? esc(slot.value) : "&mdash;"}</div>
      ${open && filled ? provenance(slot) : ""}
    </div>`;
}

/**
 * Why this field holds this value.
 *
 * When a booking is wrong the operator's first question is "where did that come
 * from?" — so the matched term and the utterance behind it are shown, not just
 * the result.
 */
function provenance(slot) {
  const trail = (slot.history || []).slice().reverse();
  const source = SOURCE_LABEL[slot.source] || slot.source;

  return `
    <div class="field-detail">
      <div class="detail-row">
        <span class="detail-key">source</span>
        <span class="detail-val">${esc(source)}${slot.at ? ` · ${clock(slot.at)}` : ""}</span>
      </div>
      ${slot.term ? `
        <div class="detail-row">
          <span class="detail-key">matched</span>
          <span class="detail-val"><code>${esc(slot.term)}</code></span>
        </div>` : ""}
      ${slot.utterance ? `<div class="detail-quote">&ldquo;${esc(slot.utterance)}&rdquo;</div>` : ""}
      <div class="detail-note">${CONF_EXPLAIN[slot.confidence] || ""}</div>
      ${slot.warnings?.length ? `<div class="detail-warn">${slot.warnings.map(esc).join("<br>")}</div>` : ""}
      ${trail.length ? `
        <div class="detail-trail">
          <div class="detail-key">was</div>
          ${trail.map((h) => `
            <div class="trail-row">
              <span class="trail-value">${esc(h.value)}</span>
              <span class="trail-meta">${CONF_LABEL[h.confidence] || ""}${h.at ? ` · ${clock(h.at)}` : ""}</span>
            </div>`).join("")}
        </div>` : ""}
    </div>`;
}

function renderIssues() {
  const issues = store.snapshot?.issues || [];
  if (!issues.length) {
    el.issues.classList.add("hidden");
    return;
  }
  el.issues.classList.remove("hidden");
  el.issues.innerHTML = issues.map((i) => `
    <div class="issue ${i.severity}">
      <span class="issue-dot"></span>
      <span><strong>${esc(i.field)}</strong> — ${esc(i.message)}</span>
    </div>`).join("");
}

/**
 * Turn a value into an input, and hand the result back to the caller.
 *
 * The edit is sent to the agent rather than applied locally: the agent owns the
 * indent, and an operator edit lands at the top of its confidence ladder so
 * nothing automatic can undo it.
 */
export function beginEdit(target, onCommit) {
  const key = target.dataset.key;
  if (!key || target.querySelector("input")) return;

  const current = store.snapshot?.indent?.fields?.[key]?.value || "";
  target.innerHTML = `<input class="field-edit" value="${esc(current)}" />`;
  const input = target.querySelector("input");
  input.focus();
  input.select();

  const commit = () => onCommit(key, input.value.trim());
  input.addEventListener("blur", commit, { once: true });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); input.blur(); }
    if (e.key === "Escape") {
      input.removeEventListener("blur", commit);
      onCommit(null, null);   // re-render, discard
    }
  });
}

export function resetIndentRenderState() {
  previousFilled = new Set();
}
