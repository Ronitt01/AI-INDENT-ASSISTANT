# Phase 6 — parallel run & cutover plan

This phase is calendar time on real production traffic, not something that can be executed
from a repo. What follows is the plan plus the one piece of config that makes a gradual
rollout possible: a per-request traffic-split decision your backend makes when a driver
starts a call.

## Rollout mechanism

Add one field to whatever issues the "start a voice session" decision today (likely the
same backend endpoint that will host [`backend/token_server.py`](../backend/token_server.py)):

```python
import hashlib

def use_new_stack(order_id: str, rollout_pct: int) -> bool:
    """Deterministic split: same order_id always lands on the same stack,
    so a driver doesn't flip mid-conversation on a retry."""
    bucket = int(hashlib.sha256(order_id.encode()).hexdigest(), 16) % 100
    return bucket < rollout_pct
```

Drive `rollout_pct` from an env var or feature-flag service you already have, not a code
change per week — bumping the percentage should be a config edit, not a deploy.

## Schedule (from the roadmap's estimate — adjust to your real ramp)

| Week | New-stack share | Gate to advance |
|---|---|---|
| 1 | 5% | No increase in dropped calls vs. Vapi baseline; no P1 errors |
| 2 | 20% | Latency P50/P90 within the 450-650ms range measured in Phase 0; cost/call tracking matches §1's ₹1.88/min model within 20% |
| 3 | 50% | Ops team confirms voice/transcript quality on a sample of real calls, not just synthetic ones |
| 4 | 100%, Vapi kept as hot fallback | Two full weeks with no rollback |
| 5+ | Decommission Vapi | Only after week 4's bar is met with margin, not on schedule pressure |

## What decides "hold" vs. "advance" each week

Pull these from [`livekit-agent/call_logging.py`](../livekit-agent/call_logging.py)'s
tables, side by side with the equivalent Vapi numbers:

- **Completion rate** — did the call reach a normal end, not a dropped WebRTC connection
  or an unhandled provider error
- **Latency** — P50/P90 turn-taking latency (STT final → first TTS byte), from the
  `call_latencies` table
- **Cost per call** — from `call_costs`, compared to the ₹1.88/min model in the roadmap's §1
- **Error rate** — from `call_errors`, anything that would have paged someone in Vapi

## Rollback

Set `rollout_pct` back to 0. Because the split is keyed on `order_id` and evaluated fresh
per call (not a sticky per-driver assignment), this takes effect on the very next call with
zero migration step — no in-flight call is affected either way since the split decision is
made once at session start.

## Explicitly not automated here

Nothing in this repo pages anyone, updates `rollout_pct`, or declares a week "passed" —
those are judgment calls for whoever owns this rollout, informed by the dashboards Phase 5
builds. Wiring `call_errors` into a real paging system (Slack webhook, PagerDuty, etc.) is
flagged as a stub in `call_logging.py` — pick the destination before Phase 6 week 1 starts,
not after the first incident.
