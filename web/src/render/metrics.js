// Call metrics.
//
// Response is measured from the caller's last word to the agent's first *audio*,
// never to its final transcript — that arrives only after the sentence has
// played and would fold the whole speaking duration into the number. Agent
// speaking time is reported separately as a duration, and interrupted turns are
// shown but excluded from the averages.

import { LATENCY_GOOD, LATENCY_WARN } from "../constants.js";
import { el, esc } from "../dom.js";
import { store } from "../store.js";

const latClass = (ms) =>
  ms == null ? "" : ms <= LATENCY_GOOD ? "lat-good" : ms <= LATENCY_WARN ? "lat-warn" : "lat-bad";

export function renderMetrics() {
  const m = store.snapshot?.metrics;
  if (!m || (!m.turns && !m.agentTalkMs && !store.connected)) {
    el["metrics-content"].innerHTML =
      `<p class="muted">Metrics appear once the call is under way.</p>`;
    return;
  }

  const rows = m.rows || [];
  const scale = Math.max(m.slowestMs || 0, LATENCY_WARN);

  el["metrics-content"].innerHTML = `
    ${summary(m)}
    ${rows.length ? turnBars(rows, scale) : waiting()}
    ${session(m)}
    <p class="lat-legend">response = caller stops speaking &rarr; agent audio starts.
    Agent speaking time is excluded; interrupted turns are left out of the averages.</p>`;
}

const summary = (m) => `
  <div class="lat-summary">
    <div class="lat-stat">
      <span class="lat-stat-label">avg response</span>
      <span class="lat-stat-value ${latClass(m.avgResponseMs)}">${m.avgResponseMs ?? "—"}<small>ms</small></span>
    </div>
    <div class="lat-stat">
      <span class="lat-stat-label">slowest</span>
      <span class="lat-stat-value ${latClass(m.slowestMs)}">${m.slowestMs ?? "—"}<small>ms</small></span>
    </div>
    <div class="lat-stat">
      <span class="lat-stat-label">barge-ins</span>
      <span class="lat-stat-value ${m.bargeIns ? "lat-warn" : ""}">${m.bargeIns ?? 0}</span>
    </div>
  </div>`;

const waiting = () => `
  <p class="metric-waiting">No replies timed yet — response is measured from the
  moment the caller stops speaking.</p>`;

const turnBars = (rows, scale) => `
  <div class="metric-section-title">response per turn</div>
  <div class="lat-bars">
    ${rows.map((r, i) => {
      const pct = r.responseMs == null ? 0 : Math.max(3, Math.round((r.responseMs / scale) * 100));
      return `
      <div class="lat-row${r.bargeIn ? " excluded" : ""}"
           title="turn ${i + 1}: ${r.responseMs ?? "—"}ms to first audio${r.bargeIn ? " — interrupted, excluded" : ""}">
        <span class="lat-turn">${i + 1}</span>
        <span class="lat-track"><span class="lat-fill ${latClass(r.responseMs)}" style="width:${pct}%"></span></span>
        <span class="lat-ms ${latClass(r.responseMs)}">${r.bargeIn ? "—" : (r.responseMs ?? "…")}</span>
      </div>`;
    }).join("")}
  </div>`;

const session = (m) => `
  <div class="metric-section-title">session</div>
  <div class="session-grid">
    <div class="session-row"><span>agent talk time</span><span>${((m.agentTalkMs || 0) / 1000).toFixed(1)}s</span></div>
    <div class="session-row"><span>share of call</span><span>${m.talkSharePct ?? 0}%</span></div>
    <div class="session-row"><span>turns</span><span>${m.turns ?? 0}</span></div>
    <div class="session-row"><span>scripts heard</span><span>${(m.scripts || []).map(esc).join(", ") || "—"}</span></div>
  </div>`;
