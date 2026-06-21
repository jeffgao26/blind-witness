import time
import os
import tempfile
import pytest
from pipeline.store import init_db, insert_event, get_active_alert, get_alerts
from pipeline.alerting import process_event
from contracts.events import StateEvent


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    init_db(path)
    yield path
    os.unlink(path)


# Deterministic stub so tests never hit the network.
def stub_reason(ctx):
    return {
        "severity": "critical" if ctx.get("current_state") == "FALL_SUSPECTED" else "warning",
        "family_note": "stub note",
        "trigger_consent_video": ctx.get("current_state") == "FALL_SUSPECTED",
    }


def feed(db, state, ts):
    ev = StateEvent(
        timestamp=ts, state=state, covariance_trace=40.0,
        duration_in_state=30.0, zone="in_frame", source="fixture",
    )
    insert_event(ev, db)
    return process_event(ev, db, reason_fn=stub_reason)


def test_anomaly_opens_one_alert(db):
    feed(db, "PRESENT_NORMAL", 1.0)
    created = feed(db, "FALL_SUSPECTED", 2.0)
    assert created is not None
    assert created["severity"] == "critical"
    assert get_active_alert(db)["trigger_state"] == "FALL_SUSPECTED"


def test_repeated_anomaly_heartbeats_do_not_duplicate(db):
    feed(db, "FALL_SUSPECTED", 1.0)
    feed(db, "FALL_SUSPECTED", 2.0)  # heartbeat
    feed(db, "FALL_SUSPECTED", 3.0)  # heartbeat
    assert len(get_alerts(db_path=db)) == 1


def test_return_to_normal_resolves_alert(db):
    feed(db, "FALL_SUSPECTED", 1.0)
    assert get_active_alert(db) is not None
    feed(db, "PRESENT_NORMAL", 2.0)
    assert get_active_alert(db) is None


def test_new_episode_after_resolution_opens_new_alert(db):
    feed(db, "FALL_SUSPECTED", 1.0)
    feed(db, "PRESENT_NORMAL", 2.0)
    feed(db, "PRESENT_STILL", 3.0)
    assert get_active_alert(db)["trigger_state"] == "PRESENT_STILL"
    assert len(get_alerts(db_path=db)) == 2


def test_calm_states_never_open_alerts(db):
    for i, s in enumerate(["PRESENT_NORMAL", "UNCERTAIN", "ABSENT"]):
        feed(db, s, float(i))
    assert get_active_alert(db) is None
    assert get_alerts(db_path=db) == []
