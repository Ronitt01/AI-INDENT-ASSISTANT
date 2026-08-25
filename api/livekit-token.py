"""Vercel serverless version of backend/token_server.py.

Deployed at /api/livekit-token, same origin as the console — which removes CORS
from the picture entirely rather than maintaining an allow-list of every origin
the console might be served from.

Why a second copy of this logic instead of importing backend/token_server.py:
that module is a long-lived FastAPI app that reads env at import and holds an
aiohttp session; a Vercel function is a cold-started handler with no lifespan.
The shared part is small and stable (mint a token, create the dispatch), so two
readable implementations beat one contorted to run in both shapes. If this
diverges, the FastAPI one is the reference.

Required environment variables (set these in the Vercel project):
    LIVEKIT_URL         wss://<project>.livekit.cloud
    LIVEKIT_API_KEY
    LIVEKIT_API_SECRET
    LIVEKIT_AGENT_NAME  optional, defaults to indent-assistant
    TOKEN_SHARED_SECRET optional, see below
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from http.server import BaseHTTPRequestHandler

from livekit import api

AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "indent-assistant")

# Tokens are short-lived on purpose. The SDK default runs for hours; a driver's
# call does not, and a leaked token is only interesting for as long as it is valid.
TOKEN_TTL = timedelta(minutes=int(os.getenv("TOKEN_TTL_MINUTES", "15")))

# Minimal gate so a public URL is not an open room-token dispenser. This is NOT a
# substitute for real auth - it is one shared string, and every caller holds the
# same one. Wire this endpoint to your app's session before it faces real drivers.
# Unset means unauthenticated, which is fine locally and not fine in production.
SHARED_SECRET = os.getenv("TOKEN_SHARED_SECRET", "")


def _config_error() -> str | None:
    missing = [k for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
               if not os.getenv(k)]
    if missing:
        return f"server is misconfigured: missing {', '.join(missing)}"
    return None


async def _ensure_dispatch(room: str) -> bool:
    """Explicitly dispatch the agent into `room`.

    The worker registers with an agent_name, which puts LiveKit in explicit-dispatch
    mode: without this call it is never assigned to the room and the caller joins to
    silence. Idempotent - a reconnect to the same order must not add a second agent.
    """
    if not AGENT_NAME:
        return False
    url = os.environ["LIVEKIT_URL"].replace("wss://", "https://").replace("ws://", "http://")
    lk = api.LiveKitAPI(url=url,
                        api_key=os.environ["LIVEKIT_API_KEY"],
                        api_secret=os.environ["LIVEKIT_API_SECRET"])
    try:
        try:
            for d in await lk.agent_dispatch.list_dispatch(room):
                if d.agent_name == AGENT_NAME:
                    return True
        except Exception:
            # 503 here just means the room does not exist yet, which is the normal
            # case: the caller has not connected. Nothing to dedupe against.
            pass
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room)
        )
        return True
    except Exception:
        # A dispatch failure still returns a usable token: the caller can connect and
        # see an empty room, which is a better failure than no call at all.
        return False
    finally:
        await lk.aclose()


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # health check
        err = _config_error()
        self._send(500 if err else 200,
                   {"error": err} if err else {"status": "ok", "agent": AGENT_NAME})

    def do_POST(self) -> None:
        err = _config_error()
        if err:
            self._send(500, {"error": err})
            return

        if SHARED_SECRET and self.headers.get("X-Token-Secret") != SHARED_SECRET:
            self._send(401, {"error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, {"error": "body must be JSON"})
            return

        user_id = str(req.get("user_id") or "").strip()
        order_id = str(req.get("order_id") or "").strip()
        if not user_id or not order_id:
            self._send(400, {"error": "user_id and order_id are required"})
            return

        room = f"indent-{order_id}"
        token = (
            api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
            .with_identity(user_id)
            .with_ttl(TOKEN_TTL)
            .with_grants(api.VideoGrants(room_join=True, room=room))
            .to_jwt()
        )
        dispatched = asyncio.run(_ensure_dispatch(room))
        self._send(200, {
            "token": token,
            "url": os.environ["LIVEKIT_URL"],
            "room": room,
            "agent_dispatched": dispatched,
        })
