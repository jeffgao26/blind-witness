"""
Reasoning layer — turns an anomaly context into a family-facing alert.

Called when the monitored person transitions INTO an anomalous state
(FALL_SUSPECTED / PRESENT_STILL). Text-only by design: Claude sees only the
abstracted state history assembled by store/baseline — never video or images.

Model: claude-haiku-4-5 — a short, structured judgment, so the cheapest/fastest
tier fits. Swap MODEL to "claude-opus-4-8" if family_note quality matters more
than cost. If the API key is missing or the call fails, reason() falls back to a
deterministic note so the pipeline never hard-crashes on the reasoning step.
"""
import json

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 512
SEVERITIES = ("info", "warning", "critical")

SYSTEM = (
    "You are the reasoning layer of Constant, a privacy-first eldercare monitor. "
    "You receive ONLY abstracted state data (labels, durations, counts) — never video or images. "
    "Judge how concerning the current situation is and write one calm, plain-language "
    "sentence a family member would read on their phone. Be accurate, not alarmist — "
    "false alarms erode trust. FALL_SUSPECTED is the most serious signal; PRESENT_STILL "
    "may simply be rest or watching TV. Never diagnose a medical condition; describe the "
    "deviation from the normal pattern."
)

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "family_note": {"type": "string"},
        "trigger_consent_video": {"type": "boolean"},
    },
    "required": ["severity", "family_note", "trigger_consent_video"],
    "additionalProperties": False,
}


def reason(ctx: dict, client=None) -> dict:
    """
    ctx: anomaly context from baseline.get_anomaly_context().
    Returns {severity, family_note, trigger_consent_video}.
    `client` is an optional anthropic.Anthropic instance (injected in tests).
    """
    if not ctx:
        return _fallback(ctx)

    prompt = (
        "Current monitoring context (state data only, no video):\n\n"
        + json.dumps(ctx, indent=2)
        + "\n\nDecide the escalation severity, write the family note, and decide whether to "
        "trigger the consent-gated video check-in (only for a critical, time-sensitive situation)."
    )
    try:
        if client is None:
            from anthropic import Anthropic  # lazy: pipeline runs offline, just falls back
            client = Anthropic()
        # Forced tool use: portable across SDK versions and returns a parsed dict.
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            tools=[{
                "name": "report_assessment",
                "description": "Report the escalation severity and the family-facing note.",
                "input_schema": RESULT_SCHEMA,
            }],
            tool_choice={"type": "tool", "name": "report_assessment"},
        )
        data = next(b.input for b in resp.content if b.type == "tool_use")
        return {
            "severity": data["severity"],
            "family_note": str(data["family_note"]).strip(),
            "trigger_consent_video": bool(data["trigger_consent_video"]),
        }
    except Exception as e:
        print(f"reasoning: Claude call failed ({e}); using fallback note")
        return _fallback(ctx)


def _fallback(ctx: dict) -> dict:
    """Deterministic note used when the LLM is unavailable — keeps the demo alive offline."""
    state = ctx.get("current_state") if ctx else None
    reason_text = ctx.get("anomaly_reason") if ctx else None
    if state == "FALL_SUSPECTED":
        return {
            "severity": "critical",
            "family_note": reason_text or "A possible fall was detected and the person has not moved since.",
            "trigger_consent_video": True,
        }
    if state == "PRESENT_STILL":
        return {
            "severity": "warning",
            "family_note": reason_text or "The person has been still for an unusually long time.",
            "trigger_consent_video": False,
        }
    return {
        "severity": "info",
        "family_note": "Monitoring is active; nothing needs attention right now.",
        "trigger_consent_video": False,
    }
