"""Emergency supervisor — turns a pipeline trigger into the consent + camera handoff.

Listens on the redis channel the pipeline publishes to when an alert decides
trigger_consent_video. On a trigger:
  1. TTS consent prompt + wait window for a refusal (redis flag / Enter).
  2. If refused -> nothing happens, monitoring is never interrupted.
  3. If no response -> request the camera (set the yield flag), wait for the
     monitoring loop to release it, run the bounded media session (live view + call),
     then clear the flag so monitoring reacquires the camera and resumes.

Isolation: this lives in emergency/, reacts to a redis message, and coordinates the
camera via plain flags. The monitoring loop imports nothing from here; it only reads
the yield flag. Run with the aiortc venv:  ~/rtcenv/bin/python -m emergency.supervisor
"""
import os
import time

import redis

from emergency.consent_video import speak, wait_for_refusal, serve_live_view, CONSENT_WINDOW
# NOTE: one-way live view only (stdlib MJPEG, no aiortc). The two-way WebRTC call lives
# in emergency/call.py as a documented v2; swap serve_live_view -> call.run_server to use it.

YIELD_KEY = "eldercare:camera_yield"
RELEASED_KEY = "eldercare:camera_released"
CHANNEL = "eldercare:consent_video"
STREAM_SECONDS = float(os.environ.get("CONSTANT_STREAM_SECONDS", "45"))
FAMILY = os.environ.get("CONSTANT_FAMILY", "your family")


def _wait_camera_free(r, timeout=8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if r.get(RELEASED_KEY):
            return True
        time.sleep(0.3)
    return False


def run_session(r) -> None:
    speak(f"Are you okay? I'm about to let {FAMILY} see this room. Say no to cancel.")
    if wait_for_refusal(CONSENT_WINDOW, r):
        speak("Okay. Staying private.")
        print("[supervisor] consent REFUSED — monitoring never interrupted.")
        return
    speak("No response. Opening a live view for your family now.")
    print("[supervisor] consent lapsed — requesting camera handoff.")
    r.set(YIELD_KEY, "1")
    if not _wait_camera_free(r):
        print("[supervisor] WARNING: monitoring didn't confirm release; proceeding anyway.")
    try:
        serve_live_view(STREAM_SECONDS)   # owns the camera, one-way MJPEG, then releases
    finally:
        r.delete(YIELD_KEY)
        r.delete(RELEASED_KEY)
        print("[supervisor] session ended — camera returned to monitoring.")


def main():
    r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"),
                       decode_responses=True)
    ps = r.pubsub()
    ps.subscribe(CHANNEL)
    print(f"[supervisor] listening on {CHANNEL} for consent-video triggers")
    for msg in ps.listen():
        if msg.get("type") != "message":
            continue
        print("[supervisor] trigger received")
        try:
            run_session(r)
        except Exception as e:
            print(f"[supervisor] session error: {e}")
            r.delete(YIELD_KEY)
            r.delete(RELEASED_KEY)


if __name__ == "__main__":
    main()
