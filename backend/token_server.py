"""Phase 2 — token backend.

Every client (web or Android) needs a short-lived LiveKit token from *your* server —
never ship LIVEKIT_API_SECRET to a browser or app. This is deliberately the only
thing this service does; wire it into your existing backend rather than running it
standalone once Phase 6 needs it to also decide new-stack-vs-Vapi routing (see
docs/ROLLOUT.md's `use_new_stack()` — that hook plugs in here, at issuance time).

Run:
    pip install -r requirements.txt
    uvicorn token_server:app --reload --port 8080
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from livekit import api
from pydantic import BaseModel

load_dotenv()

LIVEKIT_URL = os.environ["LIVEKIT_URL"]
LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]

# Tighten this before production — this is permissive for local Phase 3/4 testing.
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

# Must match the agent_name in livekit-agent/agent.py's @server.rtc_session decorator.
# Because that decorator names the agent, LiveKit puts the worker in *explicit dispatch*
# mode: it is never auto-assigned to a room, so without the dispatch created below a
# caller joins to silence. Set to "" if you switch the agent to automatic dispatch
# (i.e. drop agent_name there), i.e. this is also the ROLLOUT.md use_new_stack() hook —
# skip the dispatch and the call is free to fall through to Vapi instead.
AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "indent-assistant")

# The API is HTTP even though clients get a ws:// URL for signalling.
LIVEKIT_API_URL = LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://")

logger = logging.getLogger("token-server")

app = FastAPI(title="Indent Assistant token server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST"],
    allow_headers=["*"],
)


class TokenRequest(BaseModel):
    user_id: str
    order_id: str


class TokenResponse(BaseModel):
    token: str
    url: str
    room: str
    agent_dispatched: bool


async def ensure_agent_dispatch(room: str) -> bool:
    """Make sure exactly one `AGENT_NAME` worker is dispatched to `room`.

    Idempotent: a driver reconnecting to the same order's room must not get a second
    agent in the call. Never raises — a dispatch failure still returns a usable token
    (the caller can connect and see an agentless room) rather than failing the call.
    """
    if not AGENT_NAME:
        return False

    lk = api.LiveKitAPI(url=LIVEKIT_API_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
    try:
        try:
            existing = await lk.agent_dispatch.list_dispatch(room)
        except Exception:
            # 503 "no response from servers" simply means the room does not exist yet,
            # which is the common case: the driver has not connected. Nothing to dedupe
            # against, so fall through and create. create_dispatch creates the room.
            existing = []
        for dispatch in existing:
            if dispatch.agent_name == AGENT_NAME:
                return True
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room)
        )
        return True
    except Exception:
        logger.exception("agent dispatch failed for room %s - caller will join an empty room", room)
        return False
    finally:
        await lk.aclose()


@app.post("/livekit-token", response_model=TokenResponse)
async def issue_token(req: TokenRequest) -> TokenResponse:
    if not req.user_id or not req.order_id:
        raise HTTPException(status_code=400, detail="user_id and order_id are required")

    room = f"indent-{req.order_id}"
    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(req.user_id)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    dispatched = await ensure_agent_dispatch(room)
    return TokenResponse(token=token, url=LIVEKIT_URL, room=room, agent_dispatched=dispatched)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
