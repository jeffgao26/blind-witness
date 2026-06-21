"""
Alert orchestration — the bridge between ingested state events and the family app.

process_event() is called once per event the consumer ingests. The lifecycle:

  - Transition INTO an anomaly state (FALL_SUSPECTED / PRESENT_STILL) while no
    alert is open  →  call the reasoning layer once and open an alert.
  - Any calm state (PRESENT_NORMAL / ABSENT / UNCERTAIN) while an alert is open
    →  resolve it.

The open alert in SQLite is itself the dedup flag, so repeated heartbeats of the
same anomaly state neither spam Claude nor create duplicate alerts — one Claude
call per anomaly episode. This is what keeps the design's "minimize compute"
promise on the pipeline side.
"""
from contracts.events import StateEvent
from pipeline.baseline import get_anomaly_context
from pipeline.reasoning import reason
from pipeline.store import insert_alert, get_active_alert, resolve_active_alerts

ANOMALY_STATES = {"FALL_SUSPECTED", "PRESENT_STILL"}


def process_event(event: StateEvent, db_path: str, reason_fn=reason) -> dict | None:
    """
    React to a single ingested event. Returns the alert dict if one was created,
    otherwise None. reason_fn is injectable so tests can avoid a live Claude call.
    Call this AFTER the event has been inserted into the store.
    """
    active = get_active_alert(db_path)

    if event.state in ANOMALY_STATES and active is None:
        ctx = get_anomaly_context(db_path)
        verdict = reason_fn(ctx)
        alert_id = insert_alert(
            created_ts=event.timestamp,
            trigger_state=event.state,
            severity=verdict["severity"],
            family_note=verdict["family_note"],
            db_path=db_path,
        )
        return {
            "id": alert_id,
            "trigger_state": event.state,
            "trigger_consent_video": verdict.get("trigger_consent_video", False),
            **verdict,
        }

    if event.state not in ANOMALY_STATES and active is not None:
        resolve_active_alerts(event.timestamp, db_path)

    return None
