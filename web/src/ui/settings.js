// Connection settings modal.

import { el, toast } from "../dom.js";
import { saveSettings, store } from "../store.js";

export function openSettings() {
  el["api-base"].value = store.settings.apiBase;
  el["user-id"].value = store.settings.userId;
  el["order-id"].value = store.settings.orderId;
  el["voice-stack"].value = store.settings.voiceStack;
  el["vapi-base"].value = store.settings.vapiBase;
  el["settings-modal"].classList.remove("hidden");
}

export function closeSettings() {
  el["settings-modal"].classList.add("hidden");
}

export function commitSettings() {
  // Spread the existing settings first: this modal does not surface every key,
  // and replacing the object wholesale would silently drop the ones it omits.
  saveSettings({
    ...store.settings,
    apiBase: el["api-base"].value.trim().replace(/\/$/, ""),
    userId: el["user-id"].value.trim(),
    orderId: el["order-id"].value.trim(),
    voiceStack: el["voice-stack"].value,
    vapiBase: el["vapi-base"].value.trim().replace(/\/$/, ""),
  });
  closeSettings();
  toast(`Settings saved. Stack: ${store.settings.voiceStack}.`);
}
