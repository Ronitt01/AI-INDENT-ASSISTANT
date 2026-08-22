// The transcript feed.

import { clock, el, esc } from "../dom.js";
import { store } from "../store.js";

export function renderMessages() {
  const transcript = store.snapshot?.transcript || [];
  el.messages.innerHTML = transcript.map((m) => `
    <div class="message ${m.role}${m.bargeIn ? " barge" : ""}">
      <div class="role">
        <span>${m.role}</span>
        <span class="msg-meta">
          ${m.bargeIn ? `<span class="chip-barge" title="Caller spoke over the agent">interrupted</span>` : ""}
          ${m.language ? `<span class="chip-lang" title="Dominant script: ${esc(m.language.script)}">${esc(m.language.label)}</span>` : ""}
          ${m.at ? `<span class="msg-time">${clock(m.at)}</span>` : ""}
        </span>
      </div>
      <div class="text">${esc(m.text)}</div>
    </div>`).join("");
  el.messages.scrollTo({ top: el.messages.scrollHeight, behavior: "smooth" });
}

/** Partial STT output, shown greyed under the feed while a phrase is mid-flight. */
export function setInterim(text) {
  el.interim.textContent = text || "";
  el.interim.classList.toggle("visible", !!text);
}
