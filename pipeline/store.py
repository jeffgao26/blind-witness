import sqlite3
import time
from contextlib import contextmanager
from contracts.events import StateEvent

DB_PATH = "pipeline/constant.db"


@contextmanager
def get_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS state_events (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp          REAL NOT NULL,
                state              TEXT NOT NULL,
                covariance_trace   REAL NOT NULL,
                duration_in_state  REAL NOT NULL,
                zone               TEXT NOT NULL,
                source             TEXT NOT NULL DEFAULT 'live'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON state_events (timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_state ON state_events (state)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                created_ts     REAL NOT NULL,
                trigger_state  TEXT NOT NULL,
                severity       TEXT NOT NULL,
                family_note    TEXT NOT NULL,
                resolved       INTEGER NOT NULL DEFAULT 0,
                resolved_ts    REAL,
                clip_path      TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alert_resolved ON alerts (resolved)")


def insert_event(event: StateEvent, db_path: str = DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute("""
            INSERT INTO state_events (timestamp, state, covariance_trace, duration_in_state, zone, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            event.timestamp,
            event.state,
            event.covariance_trace,
            event.duration_in_state,
            event.zone,
            event.source,
        ))


# ------------------------------------------------------------------
# Query layer — assembles context for reasoning.py
# ------------------------------------------------------------------

def get_recent_events(limit: int = 20, db_path: str = DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM state_events
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_latest_event(db_path: str = DB_PATH) -> dict | None:
    with get_conn(db_path) as conn:
        row = conn.execute("""
            SELECT * FROM state_events ORDER BY timestamp DESC LIMIT 1
        """).fetchone()
    return dict(row) if row else None


def get_events_since(since_ts: float, db_path: str = DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM state_events
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """, (since_ts,)).fetchall()
    return [dict(r) for r in rows]


def get_reasoning_context(db_path: str = DB_PATH) -> dict:
    """
    Assembles the context dict passed to reasoning.py for the Claude call.
    Returns current state, duration, recent history, and occurrence counts.
    """
    now = time.time()
    latest = get_latest_event(db_path)
    if not latest:
        return {}

    # Last 60 minutes of events
    recent = get_events_since(now - 3600, db_path)

    # How many times FALL_SUSPECTED occurred in last hour
    fall_count = sum(1 for e in recent if e["state"] == "FALL_SUSPECTED")

    # How many times PRESENT_STILL occurred in last hour
    still_count = sum(1 for e in recent if e["state"] == "PRESENT_STILL")

    return {
        "current_state": latest["state"],
        "duration_in_state": latest["duration_in_state"],
        "covariance_trace": latest["covariance_trace"],
        "time_of_day": time.strftime("%H:%M", time.localtime(latest["timestamp"])),
        "recent_history": [
            {"state": e["state"], "duration": e["duration_in_state"], "timestamp": e["timestamp"]}
            for e in recent[-10:]
        ],
        "fall_suspected_last_hour": fall_count,
        "present_still_last_hour": still_count,
    }


# ------------------------------------------------------------------
# Alerts — created on transition into an anomalous state, resolved on return
# to a calm state. The active (unresolved) alert is what the family app shows.
# ------------------------------------------------------------------

def insert_alert(
    created_ts: float,
    trigger_state: str,
    severity: str,
    family_note: str,
    clip_path: str | None = None,
    db_path: str = DB_PATH,
) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute("""
            INSERT INTO alerts (created_ts, trigger_state, severity, family_note, clip_path)
            VALUES (?, ?, ?, ?, ?)
        """, (created_ts, trigger_state, severity, family_note, clip_path))
        return cur.lastrowid


def get_active_alert(db_path: str = DB_PATH) -> dict | None:
    """The most recent unresolved alert, or None. Drives the family-view red flip."""
    with get_conn(db_path) as conn:
        row = conn.execute("""
            SELECT * FROM alerts WHERE resolved = 0 ORDER BY created_ts DESC LIMIT 1
        """).fetchone()
    return dict(row) if row else None


def resolve_active_alerts(resolved_ts: float, db_path: str = DB_PATH) -> int:
    """Mark every open alert resolved. Returns how many were closed."""
    with get_conn(db_path) as conn:
        cur = conn.execute("""
            UPDATE alerts SET resolved = 1, resolved_ts = ? WHERE resolved = 0
        """, (resolved_ts,))
        return cur.rowcount


def get_alerts(limit: int = 20, db_path: str = DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM alerts ORDER BY created_ts DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]
