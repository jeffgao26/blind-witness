"""
Baseline anomaly context for the reasoning layer.

Since we're focused on fall detection (not routine tracking), baseline's job is
to enrich the reasoning context with recent history signals — not to flag
time-of-day deviations. Scalability hook: add per-hour expected-zone logic here
when routine tracking is added.
"""
from pipeline.store import get_reasoning_context, get_events_since
import time


def get_anomaly_context(db_path: str = "pipeline/constant.db") -> dict:
    """
    Returns enriched context for the Claude reasoning call.
    Includes current state, recent history, and fall-specific signals.
    """
    ctx = get_reasoning_context(db_path)
    if not ctx:
        return {}

    ctx["is_anomalous"] = _is_anomalous(ctx)
    ctx["anomaly_reason"] = _anomaly_reason(ctx)
    return ctx


def _is_anomalous(ctx: dict) -> bool:
    state = ctx.get("current_state")
    return state in ("FALL_SUSPECTED", "PRESENT_STILL")


def _anomaly_reason(ctx: dict) -> str | None:
    state = ctx.get("current_state")
    duration = ctx.get("duration_in_state", 0)

    if state == "FALL_SUSPECTED":
        return f"Fall signature detected — person has been motionless in an unusual position for {int(duration)}s."
    if state == "PRESENT_STILL":
        return f"Person has been motionless in frame for {int(duration)}s."
    return None
