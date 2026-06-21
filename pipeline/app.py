"""
Flask backend — serves the family-facing UI and the debug dashboard.

Routes:
  GET /               → family.html
  GET /debug          → debug.html
  GET /api/status     → {state, zone, covariance_trace, duration_in_state, ts, active_alert}
  GET /api/events     → last N state events (for the debug sparkline)
  GET /api/alerts     → alert history
  GET /clip/<id>      → serve consent video (if clip_path is set on the alert)
"""
import os
import mimetypes
from flask import Flask, render_template, jsonify, abort, send_file, request
from pipeline.store import init_db, get_latest_event, get_recent_events, get_active_alert, get_alerts

DB_PATH = os.environ.get("CONSTANT_DB", "pipeline/constant.db")
# Where the family browser fetches the consent-gated one-way live view (MJPEG).
# Default assumes you tunnel the Pi's :8090 to localhost (ssh -L 8090:localhost:8090),
# which avoids granting the browser LAN access. Override with the Pi's LAN IP if you
# view the page directly on the network.
PI_MEDIA_URL = os.environ.get("CONSTANT_PI_URL", "http://localhost:8090")

app = Flask(__name__, template_folder="../templates", static_folder="../static")

with app.app_context():
    init_db(DB_PATH)


def _db():
    return DB_PATH


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------

@app.get("/")
def family():
    return render_template("family.html", pi_media_url=PI_MEDIA_URL)


@app.get("/debug")
def debug():
    return render_template("debug.html")


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

@app.get("/api/status")
def api_status():
    latest = get_latest_event(_db())
    active = get_active_alert(_db())
    if latest is None:
        return jsonify({"state": None, "active_alert": None})
    return jsonify({
        "state": latest["state"],
        "zone": latest["zone"],
        "covariance_trace": latest["covariance_trace"],
        "duration_in_state": latest["duration_in_state"],
        "ts": latest["timestamp"],
        "active_alert": dict(active) if active else None,
    })


@app.get("/api/events")
def api_events():
    limit = min(int(request.args.get("limit", 60)), 500)
    events = get_recent_events(limit=limit, db_path=_db())
    return jsonify(events)


@app.get("/api/alerts")
def api_alerts():
    limit = min(int(request.args.get("limit", 20)), 200)
    alerts = get_alerts(limit=limit, db_path=_db())
    return jsonify(alerts)


@app.get("/clip/<int:alert_id>")
def serve_clip(alert_id: int):
    alerts = get_alerts(limit=200, db_path=_db())
    alert = next((a for a in alerts if a["id"] == alert_id), None)
    if alert is None or not alert.get("clip_path"):
        abort(404)
    clip = alert["clip_path"]
    if not os.path.isfile(clip):
        abort(404)
    mime, _ = mimetypes.guess_type(clip)
    return send_file(clip, mimetype=mime or "video/mp4")


if __name__ == "__main__":
    app.run(debug=True, port=5050)
