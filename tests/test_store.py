import time
import pytest
import tempfile
import os
from pipeline.store import init_db, insert_event, get_latest_event, get_recent_events, get_reasoning_context
from contracts.events import StateEvent


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    init_db(path)
    yield path
    os.unlink(path)


def make_event(state="PRESENT_NORMAL", seconds_ago=0, source="fixture"):
    return StateEvent(
        timestamp=time.time() - seconds_ago,
        state=state,
        covariance_trace=20.0,
        duration_in_state=10.0,
        zone="in_frame",
        source=source,
    )


def test_insert_and_retrieve(db):
    insert_event(make_event("PRESENT_NORMAL"), db)
    latest = get_latest_event(db)
    assert latest["state"] == "PRESENT_NORMAL"


def test_latest_event_is_most_recent(db):
    insert_event(make_event("PRESENT_NORMAL", seconds_ago=60), db)
    insert_event(make_event("FALL_SUSPECTED", seconds_ago=0), db)
    latest = get_latest_event(db)
    assert latest["state"] == "FALL_SUSPECTED"


def test_empty_db_returns_none(db):
    assert get_latest_event(db) is None


def test_empty_db_reasoning_context_returns_empty(db):
    ctx = get_reasoning_context(db)
    assert ctx == {}


def test_reasoning_context_has_required_keys(db):
    insert_event(make_event("FALL_SUSPECTED"), db)
    ctx = get_reasoning_context(db)
    for key in ("current_state", "duration_in_state", "time_of_day", "recent_history",
                "fall_suspected_last_hour", "present_still_last_hour"):
        assert key in ctx


def test_fall_count_in_context(db):
    insert_event(make_event("FALL_SUSPECTED", seconds_ago=30), db)
    insert_event(make_event("FALL_SUSPECTED", seconds_ago=10), db)
    insert_event(make_event("PRESENT_NORMAL", seconds_ago=5), db)
    ctx = get_reasoning_context(db)
    assert ctx["fall_suspected_last_hour"] == 2


def test_source_column_persisted(db):
    insert_event(make_event("PRESENT_NORMAL", source="fixture"), db)
    latest = get_latest_event(db)
    assert latest["source"] == "fixture"


def test_recent_events_order(db):
    for i in range(5):
        insert_event(make_event("PRESENT_NORMAL", seconds_ago=100 - i * 10), db)
    events = get_recent_events(limit=5, db_path=db)
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)
