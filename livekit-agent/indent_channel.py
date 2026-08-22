"""The data channel between the agent and the operator console.

Two directions:

* **out** — the agent publishes indent state; the console renders it.
* **in** — the operator publishes a corrected field value; it lands at EDITED,
  the top of the confidence ladder, so a human fixing a mis-heard city is not
  undone by the model mentioning the wrong one again later in the call.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

logger = logging.getLogger("indent-assistant.channel")

STATE_TOPIC = "indent-state"
EDIT_TOPIC = "operator-edit"


def make_publisher(room: Any, loop: asyncio.AbstractEventLoop) -> Callable[[dict], None]:
    """Build the sync callback IndentSession calls whenever state changes.

    ``publish_data`` is a coroutine but the change callback is synchronous, so it
    has to be *scheduled* rather than called. Calling it directly produces an
    un-awaited coroutine that never sends anything: the console sits empty for
    the whole call with nothing but a RuntimeWarning to show for it.

    Fire-and-forget by design — a UI that misses one update gets the next, and a
    publish failure must never take down a live call.
    """

    def publish(snapshot: dict) -> None:
        payload = json.dumps(snapshot).encode("utf-8")

        async def _send() -> None:
            try:
                await room.local_participant.publish_data(
                    payload, topic=STATE_TOPIC, reliable=True
                )
            except Exception:
                logger.exception("failed to publish indent state")

        try:
            asyncio.run_coroutine_threadsafe(_send(), loop)
        except Exception:
            logger.exception("failed to schedule indent state publish")

    return publish


def parse_operator_edit(packet: Any) -> tuple[str, str] | None:
    """Decode an operator correction, or None if this packet is not one.

    Returns ``(field, value)``; an empty value means "clear this field".
    """
    if getattr(packet, "topic", None) != EDIT_TOPIC:
        return None
    try:
        payload = json.loads(bytes(packet.data).decode("utf-8"))
        return str(payload["field"]), str(payload.get("value", ""))
    except Exception:
        logger.exception("malformed operator edit")
        return None
