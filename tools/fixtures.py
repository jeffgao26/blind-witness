"""
Writes a scripted event timeline to SQLite for pipeline dev/testing.
Simulates: normal presence → uncertain → fall suspected

Usage:
    python tools/fixtures.py
    python tools/fixtures.py --reset   # clears existing events first
"""
import sys
import time
from pipeline.store import init_db, insert_event
from contracts.events import StateEvent

DB_PATH = "pipeline/constant.db"

def reset(db_path: str) -> None:
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM state_events")
        print("Cleared existing events.")


def run(db_path: str = DB_PATH) -> None:
    init_db(db_path)

    now = time.time()

    timeline = [
        # (seconds_ago, state, covariance_trace, duration_in_state, zone)
        (600, "PRESENT_NORMAL",  20.0,  600.0, "in_frame"),
        (540, "PRESENT_NORMAL",  18.0,  540.0, "in_frame"),
        (480, "PRESENT_NORMAL",  22.0,  480.0, "in_frame"),
        (420, "PRESENT_NORMAL",  25.0,  420.0, "in_frame"),
        (360, "PRESENT_NORMAL",  30.0,  360.0, "in_frame"),
        (300, "PRESENT_NORMAL",  28.0,  300.0, "in_frame"),
        (240, "UNCERTAIN",       180.0,  10.0, "in_frame"),   # covariance spikes
        (220, "UNCERTAIN",       220.0,  30.0, "in_frame"),
        (200, "UNCERTAIN",       260.0,  50.0, "in_frame"),
        (180, "FALL_SUSPECTED",  40.0,   30.0, "in_frame"),   # confirmed after window
        (120, "FALL_SUSPECTED",  38.0,   90.0, "in_frame"),
        (60,  "FALL_SUSPECTED",  42.0,  150.0, "in_frame"),
    ]

    for (seconds_ago, state, cov, duration, zone) in timeline:
        event = StateEvent(
            timestamp=now - seconds_ago,
            state=state,
            covariance_trace=cov,
            duration_in_state=duration,
            zone=zone,
            source="fixture",
        )
        insert_event(event, db_path)

    print(f"Inserted {len(timeline)} fixture events into {db_path}")


if __name__ == "__main__":
    reset_first = "--reset" in sys.argv
    if reset_first:
        reset(DB_PATH)
    run(DB_PATH)

    # Print the reasoning context so you can verify immediately
    from pipeline.store import get_reasoning_context
    import json
    ctx = get_reasoning_context(DB_PATH)
    print("\nReasoning context:")
    print(json.dumps(ctx, indent=2))
