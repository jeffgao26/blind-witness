"""Emergency consent-gated live view — the ONE place video ever leaves the device.

  >>> STRUCTURALLY ISOLATED. Look at the imports: cv2, redis, stdlib. NOTHING from
  >>> device/. The always-on monitoring loop (device/monitoring_loop.py) has no import,
  >>> reference, or call path to this module — verify: grep -ri emergency device/
  >>> This module opens its OWN camera handle, only when explicitly triggered, only
  >>> after the consent sequence lapses.

Flow:
  1. Local TTS asks the monitored person: "Are you okay? ... say no to cancel."
  2. Wait a fixed window for a refusal (a redis flag the touchscreen/family app or
     `redis-cli set eldercare:consent cancel` can set, or Enter in this terminal).
  3. If refused  -> nothing opens. The video path is never reached.
     If no answer -> open a LIVE one-way MJPEG view for the family for N seconds,
     then stop and release the camera. Frames are streamed live and NEVER written to
     disk — there is nothing to store or leak.

Run on the Pi (standalone, for the demo):
    cd ~/blind-witness && python3 -m emergency.consent_video
Env:
    CONSTANT_AUDIO_DEV  ALSA output for TTS (e.g. plughw:2,0 for the 3.5mm jack; default "default")
    REDIS_URL           default redis://localhost:6379
"""
import os
import select
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import redis

CONSENT_KEY = "eldercare:consent"     # set to "cancel" to refuse
PORT = 8090
CONSENT_WINDOW = 10.0                  # seconds to allow a refusal
STREAM_SECONDS = 30.0                  # how long the family view stays open
W, H = 640, 480


def speak(text: str) -> None:
    dev = os.environ.get("CONSTANT_AUDIO_DEV", "default")
    print(f"[tts] {text}")
    try:
        p = subprocess.Popen(["espeak-ng", "-s", "150", "--stdout", text],
                             stdout=subprocess.PIPE)
        subprocess.run(["aplay", "-q", "-D", dev], stdin=p.stdout)
        p.wait()
    except FileNotFoundError:
        print("[tts] espeak-ng/aplay not found — install: sudo apt install espeak-ng alsa-utils")


def wait_for_refusal(seconds: float, r) -> bool:
    """True if the person refused (redis flag or Enter) within the window."""
    try:
        r.delete(CONSENT_KEY)
    except Exception:
        pass
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if r.get(CONSENT_KEY):
                return True
        except Exception:
            pass
        # non-blocking stdin check (Enter = refuse), works in a terminal/SSH session
        if select.select([sys.stdin], [], [], 0.2)[0]:
            sys.stdin.readline()
            return True
    return False


def serve_live_view(seconds: float) -> None:
    """Open the camera, serve a one-way MJPEG view for `seconds`, then stop. No disk."""
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    if not cap.isOpened():
        print("[emergency] could not open camera"); return

    state = {"jpeg": None, "run": True}
    lock = threading.Lock()

    def grab():
        while state["run"]:
            ok, frame = cap.read()
            if not ok:
                continue
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                with lock:
                    state["jpeg"] = buf.tobytes()   # held in memory only; never written

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path != "/emergency":
                self.send_response(302); self.send_header("Location", "/emergency"); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while state["run"]:
                    with lock:
                        jpeg = state["jpeg"]
                    if jpeg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg + b"\r\n")
                    time.sleep(1 / 15)
            except (BrokenPipeError, ConnectionResetError):
                pass

    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=grab, daemon=True).start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"[emergency] LIVE view open for family: http://<pi-ip>:{PORT}/emergency  ({seconds:.0f}s)")
    time.sleep(seconds)

    state["run"] = False
    srv.shutdown()
    cap.release()
    print("[emergency] live view closed; camera released; no frame was ever stored.")


def run_emergency(family: str = "your family",
                  consent_window: float = CONSENT_WINDOW,
                  stream_seconds: float = STREAM_SECONDS) -> None:
    r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"),
                       decode_responses=True)
    speak(f"Are you okay? I'm about to let {family} see this room. "
          f"Say no, or press enter, to cancel.")
    if wait_for_refusal(consent_window, r):
        speak("Okay. Staying private.")
        print("[emergency] CONSENT REFUSED — video path never opened.")
        return
    speak("No response. Opening a live view for your family now.")
    print("[emergency] consent lapsed — opening one-way live view.")
    serve_live_view(stream_seconds)


if __name__ == "__main__":
    run_emergency()
