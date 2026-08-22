"""What `upsert_indent` and `confirm_indent` actually do, independent of vendor.

Two stacks now call these tools: LiveKit + Gemini via ``runtime.assistant``, and
Vapi via ``vapi_bridge.webhook``. The wire formats differ — LiveKit hands us typed
function arguments, Vapi posts JSON to a webhook — but the *meaning* of a tool
call must not. Keeping one implementation here is what stops the two paths
quietly diverging into two different products.

Returns plain dicts; each caller serialises them however its transport wants.
"""

from __future__ import annotations

from typing import Any

from indent.domain import FIELD_BY_KEY, IndentSession


def last_user_text(session: IndentSession) -> str | None:
    """The caller's most recent utterance, for provenance on an extracted value."""
    for utterance in reversed(session.transcript):
        if utterance.role == "user":
            return utterance.text
    return None


def upsert_indent(
    session: IndentSession,
    field: str,
    value: str,
    *,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Record one field. Re-calling for the same field replaces the value."""
    if field not in FIELD_BY_KEY:
        # A hallucinated field name is a model error, not a crash. Say so in the
        # tool result so the model can correct itself on the next turn.
        return {
            "ok": False,
            "problem": f"unknown field {field!r}",
            "validFields": sorted(FIELD_BY_KEY),
        }

    changed, warnings = session.apply_extraction(
        field, value, confirmed=confirmed, utterance=last_user_text(session)
    )
    if not changed and warnings:
        return {"ok": False, "problem": warnings[0]}

    payload: dict[str, Any] = {
        "ok": True,
        "field": field,
        "stored": session.state.value(field),
        "remaining": [FIELD_BY_KEY[f.key].label for f in session.state.missing()],
    }
    # Handed back so the model can say the assumption out loud rather than
    # letting it slip through silently.
    if warnings:
        payload["assumptions"] = warnings
    return payload


def confirm_indent(session: IndentSession) -> dict[str, Any]:
    """Finalise the indent, or explain why it cannot be finalised yet."""
    ok, reasons = session.confirm()
    if ok:
        return {"ok": True, "indent": session.state.to_plain()}
    return {"ok": False, "problems": reasons}
