// Which voice stack this console is driving.
//
// Both modules expose the same four functions, so everything above this line is
// stack-agnostic. The choice is a setting rather than a build flag so the two can
// be compared back-to-back in one sitting — which is the only reason to keep two
// stacks alive at all.
//
// Loaded on demand: eagerly importing both pulls livekit-client *and* the Vapi
// SDK into the first paint for a console that will only ever use one of them.
//
// The stack is pinned for the duration of a call. Switching mid-call would route
// disconnect() at a different transport than connect() used, leaving the previous
// one's sockets open and the indent panel bound to a call that has ended.

import { store } from "./store.js";

// Vapi is deliberately gone: this project exists to replace it, and the whole
// point of the self-hosted stack is that there is only one transport to keep alive.
// (The original console kept both so they could be A/B'd in one sitting.)
const LOADERS = {
  livekit: () => import("./livekit/call.js"),
};

export const STACK_LABEL = { livekit: "LiveKit + Sarvam" };

function stackName() {
  const name = store.settings.voiceStack;
  if (!LOADERS[name]) {
    console.warn(`unknown voiceStack "${name}", using livekit`);
    return "livekit";
  }
  return name;
}

export async function connect(handlers) {
  const name = stackName();
  try {
    store.activeStack = await LOADERS[name]();
  } catch (err) {
    console.error(err);
    handlers.onCallState("idle");
    const { toast } = await import("./dom.js");
    toast(`Could not load the ${name} transport.`);
    return;
  }
  return store.activeStack.connect(handlers);
}

// The three below are only meaningful during a call, so with no pinned stack
// they are no-ops rather than errors.

export async function disconnect() {
  const stack = store.activeStack;
  store.activeStack = null;
  if (stack) await stack.disconnect();
}

export async function setMuted(muted) {
  if (store.activeStack) await store.activeStack.setMuted(muted);
}

export function sendEdit(field, value) {
  return store.activeStack ? store.activeStack.sendEdit(field, value) : false;
}
