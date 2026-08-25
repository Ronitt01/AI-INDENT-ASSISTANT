"""Phase 1b — the agent worker: STT -> LLM -> TTS per call, replacing "Vapi".

Run against the local dev LiveKit server from docker-compose.yml:

    docker compose up -d
    pip install -r requirements.txt
    python agent.py dev

Test with LiveKit's own Agents Playground first (isolates "is my pipeline broken"
from "is my app's integration broken"), before wiring up web/ or android/.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    MetricsCollectedEvent,
    RunContext,
    TurnHandlingOptions,
    cli,
    function_tool,
    metrics,
)
from livekit.plugins import openai as lk_openai
from livekit.plugins import silero

# Local ONNX turn detector. This import is deprecated in favour of
# livekit.agents.inference.TurnDetector, but that one calls a LiveKit Cloud gateway
# first (it is what logged "cloud turn detector failed (401 Unauthorized)" on every
# call against the self-hosted server) and only falls back to a local model. A
# self-hosted stack wants the local model directly, so keep this until the local
# path has a non-deprecated home. Weights: `python agent.py download-files`.
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import indent_tools
from call_logging import CallRecorder
from indent.domain import IndentSession
from indent_channel import make_publisher, parse_operator_edit
from indent_prompts import GREETING_INSTRUCTIONS, SYSTEM_PROMPT
from sarvam_plugins import STT as SarvamSTT
from sarvam_plugins import STTOptions as SarvamSTTOptions
from sarvam_plugins import TTS as SarvamTTS
from sarvam_plugins import TTSOptions as SarvamTTSOptions

load_dotenv()

# The cost/latency summary contains the rupee sign, which a cp1252 Windows console
# cannot encode: logging raised UnicodeEncodeError and silently dropped the line on
# every call. Force UTF-8 on whatever stream handlers logging ends up with.
for _h in logging.getLogger().handlers:
    if isinstance(_h, logging.StreamHandler) and hasattr(_h.stream, "reconfigure"):
        _h.stream.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger("indent-assistant")

# STT and TTS need DIFFERENT language codes - they are not interchangeable:
#   * Saaras accepts "unknown" for auto-detect, which measured IDENTICAL accuracy to
#     naming the language on all 11 testable languages, and fixes 6 of 12 that a
#     hardcoded hi-IN mangles (English, Punjabi, Bengali, Kannada, Malayalam, Odia).
#   * Bulbul REJECTS "unknown" outright (validation error), so TTS must name a real
#     language. That is harmless: Bulbul is script-driven, not language_code-driven -
#     hi-IN reads Telugu text back at 0% WER. Verified against the live API Aug 2026.
STT_LANGUAGE_CODE = os.getenv("SARVAM_STT_LANGUAGE_CODE", "unknown")
TTS_LANGUAGE_CODE = os.getenv("SARVAM_TTS_LANGUAGE_CODE", os.getenv("SARVAM_LANGUAGE_CODE", "hi-IN"))
LLM_MODEL = os.getenv("SARVAM_LLM_MODEL", "sarvam-105b-conversations")
TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "shubh")  # Phase-0 A/B winner goes here
USE_GROQ_FALLBACK = os.getenv("USE_GROQ_FALLBACK", "false").lower() == "true"
USE_OPENROUTER = os.getenv("USE_OPENROUTER", "false").lower() == "true"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "stealth/ox-alpha")

class IndentAssistant(Agent):
    """The conversational agent plus the two tools that fill the indent.

    Extraction happens through `upsert_indent`: the model calls it as it learns each
    field, and the operator console renders whatever the call carried. Verified that
    sarvam-105b-conversations does emit tool calls - one Hinglish sentence ("Nashik se
    Pune, 20 ton steel, kal subah, open body truck") produced six correct
    upsert_indent calls. The lexicon in indent.extraction runs one tier lower and
    catches fields the model fails to emit.
    """

    def __init__(self, indent: IndentSession) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self.indent = indent

    async def on_enter(self) -> None:
        self.session.generate_reply(instructions=GREETING_INSTRUCTIONS)

    @function_tool()
    async def upsert_indent(
        self,
        context: RunContext,
        field: str,
        value: str,
        confirmed: bool = False,
    ) -> str:
        """Record one field of the transport indent.

        Call this as soon as a value is known, once per field. Calling it again for
        the same field replaces the previous value.

        Args:
            field: One of pickupLocation, deliveryLocation, material, quantity,
                vehicleType, pickupDate, deliveryDate, procurementType.
            value: The value in English, normalised.
            confirmed: True only if the caller explicitly confirmed this value.
        """
        return json.dumps(
            indent_tools.upsert_indent(self.indent, field, value, confirmed=confirmed)
        )

    @function_tool()
    async def confirm_indent(self, context: RunContext) -> str:
        """Finalise the indent. Only call this after the caller has confirmed the
        summary. Fails if anything is missing or inconsistent."""
        return json.dumps(indent_tools.confirm_indent(self.indent))


def _build_llm():
    if USE_OPENROUTER:
        # Same trade as the Groq branch below: OpenRouter fronts providers that are
        # mostly US-hosted, so the LLM leg leaves India even while STT/TTS stay on
        # Sarvam. Worth it to try a model Sarvam does not host; watch the LLM TTFT in
        # the per-call metrics before keeping it.
        logger.warning(
            "USE_OPENROUTER=true: LLM leg now routes through OpenRouter (%s) instead of "
            "Sarvam — the round trip leaves India, so check LLM latency in the call metrics.",
            OPENROUTER_MODEL,
        )
        # with_openrouter reads OPENROUTER_API_KEY itself and sets the OpenRouter
        # base_url; site_url/app_name are the optional HTTP-Referer / X-Title headers
        # that put this app on OpenRouter's leaderboards, and are skipped when unset.
        return lk_openai.LLM.with_openrouter(
            model=OPENROUTER_MODEL,
            site_url=os.getenv("OPENROUTER_SITE_URL") or None,
            app_name=os.getenv("OPENROUTER_APP_NAME") or None,
        )

    if USE_GROQ_FALLBACK:
        from livekit.plugins import groq

        logger.warning(
            "USE_GROQ_FALLBACK=true: LLM leg now round-trips to Groq's (likely US) infra even "
            "though STT/TTS stay on Sarvam — see roadmap §2, this can eat the whole latency "
            "budget on its own. Only use this if Phase 0 found Sarvam's own LLM too slow."
        )
        return groq.LLM(model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"))

    # Confirmed against docs.sarvam.ai: the v1 chat completions endpoint is
    # OpenAI-compatible, so no custom adapter is needed for the LLM leg.
    return lk_openai.LLM(
        model=LLM_MODEL,
        base_url="https://api.sarvam.ai/v1",
        api_key=os.environ["SARVAM_API_KEY"],
    )


def _text_of(item):
    """Pull plain text out of a conversation item, whatever shape it arrives in."""
    text = getattr(item, "text_content", None) or getattr(item, "content", None)
    if not text:
        return None
    return " ".join(str(t) for t in text) if isinstance(text, list) else str(text)


server = AgentServer()


@server.rtc_session(agent_name="indent-assistant")
async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    # The indent state the operator console renders. on_change fires on every field
    # update and publishes a snapshot over the "indent-state" data topic; the console
    # is a pure renderer and never holds authoritative state.
    loop = asyncio.get_running_loop()
    indent = IndentSession(call_id=ctx.job.id, on_change=make_publisher(ctx.room, loop))

    session = AgentSession(
        stt=SarvamSTT(params=SarvamSTTOptions(language_code=STT_LANGUAGE_CODE)),
        llm=_build_llm(),
        tts=SarvamTTS(params=SarvamTTSOptions(language_code=TTS_LANGUAGE_CODE, speaker=TTS_SPEAKER)),
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            # NO semantic turn detector here, deliberately. Wiring MultilingualModel in
            # (the non-deprecated way) made it genuinely active for the first time - and
            # the caller's turn then never closed: interim text grew in the console,
            # "turns: 0", empty indent. While it was passed the deprecated way it was
            # ignored, the session ran VAD-only, and turns committed fine. So the model
            # is the thing that broke it, and VAD-only is the configuration that works.
            # Revisit only with a call recording to test against, never live.
            #
            # min_delay carries the job instead: Sarvam's VAD emits END_SPEECH at every
            # short pause, and the framework default of 0.5s ends the turn mid-sentence
            # for anyone who pauses to think. max_delay caps a rambling caller.
            endpointing={"min_delay": 1.0, "max_delay": 5.0},
        ),
    )

    call = CallRecorder(session_id=ctx.job.id, room=ctx.room.name)

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        call.record_metrics(ev.metrics)
        metrics.log_metrics(ev.metrics)

    @ctx.room.on("data_received")
    def _on_data(packet) -> None:
        edit = parse_operator_edit(packet)
        if edit and indent.apply_operator_edit(*edit):
            logger.info("operator edited %s -> %r", *edit)

    @session.on("conversation_item_added")
    def _on_conversation_item(ev) -> None:
        call.record_transcript_item(ev.item)
        item = getattr(ev, "item", None)
        text = _text_of(item)
        if not text:
            return
        role = getattr(item, "role", None)
        if role == "user":
            indent.add_user_speech(text)
        elif role == "assistant":
            indent.add_agent_speech(text)

    # Latency is measured to the moment audio STARTS, never to the final transcript:
    # that lands only after the sentence has finished playing and would fold the whole
    # speaking duration into the number. mark_agent_speech_start is idempotent because
    # more than one event can signal the same utterance.
    @session.on("speech_created")
    def _on_speech_created(_ev) -> None:
        indent.mark_agent_speech_start()

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:
        if getattr(ev, "new_state", None) == "speaking":
            indent.mark_agent_speech_start()
        elif getattr(ev, "old_state", None) == "speaking":
            indent.mark_agent_speech_end()

    @session.on("error")
    def _on_error(ev) -> None:
        inner = ev.error
        call.record_error(
            error=repr(getattr(inner, "error", inner)),
            recoverable=bool(getattr(inner, "recoverable", False)),
        )
        indent.add_system_note("A problem occurred on the call.")

    async def _on_shutdown() -> None:
        call.finalize()
        logger.info(
            "call finished: %s",
            json.dumps({"indent": indent.state.to_plain(), "metrics": indent.metrics_summary()}),
        )

    ctx.add_shutdown_callback(_on_shutdown)

    await session.start(agent=IndentAssistant(indent), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)
