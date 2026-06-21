"""DEBUG / DEMO viewer — streams the annotated camera feed to a browser.

  >>> DEV TOOL ONLY. Deliberately retains/transmits frames; NOT the privacy path.

Runs the REAL pipeline at the PRODUCTION resolution (320x240) so what you see matches
device/monitoring_loop.py exactly: blob.detect_blob -> KalmanFilter -> StateMachine.
Draws the FLOOR LINE (the fall threshold) and a live cy readout so you can calibrate
FLOOR_FRAC to this camera: if a fall's centroid doesn't cross the line, lower FLOOR_FRAC
in device/state_machine.py.

Run on the Pi:  python3 tools/debug_view.py
View (no Chrome LAN needed):  ssh -L 8080:localhost:8080 ... then http://localhost:8080
"""
import os
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from device.kalman import KalmanFilter, LOW_COV, HIGH_COV
from device.state_machine import StateMachine, FLOOR_FRAC, FRAME_H, SPEED_STILL_THRESHOLD
from blob import make_bg, detect_blob

PORT = 8080
W, H = 320, 240          # production resolution
DW, DH = 960, 720        # display (x3)
COLORS = {
    "PRESENT_NORMAL": (0, 200, 0), "PRESENT_STILL": (0, 200, 0),
    "UNCERTAIN": (0, 180, 255), "ABSENT": (150, 150, 150),
    "FALL_SUSPECTED": (0, 0, 255),
}
_latest = {"jpeg": None}
_lock = threading.Lock()


def capture_loop():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    fgbg = make_bg()
    kf = None
    sm = StateMachine(emit_fn=lambda e: None, frame_h=H)   # match capture height
    last = None
    floor_disp = int(FLOOR_FRAC * DH)                      # floor line in display coords

    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.03); continue
        det = detect_blob(frame, fgbg)
        now = time.time()
        dt = (now - last) if last else 0.1
        last = now
        if det is not None:
            cx, cy = det[4], det[5]
            if kf is None:
                kf = KalmanFilter(cx, cy)
            kf.predict(dt); kf.update(cx, cy)
        elif kf is not None:
            kf.predict(dt)
        if kf is not None:
            sm.update(kf, det, now=now)

        disp = cv2.resize(frame, (DW, DH))
        color = COLORS.get(sm.state, (255, 255, 255))
        # floor line
        cv2.line(disp, (0, floor_disp), (DW, floor_disp), (80, 80, 255), 2)
        cv2.putText(disp, "floor zone", (10, floor_disp - 8), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (80, 80, 255), 1)
        # detection box + centroid
        if det is not None:
            x, y, w, h, cx, cy, _ = det
            sx, sy = DW / W, DH / H
            cv2.rectangle(disp, (int(x*sx), int(y*sy)), (int((x+w)*sx), int((y+h)*sy)), color, 2)
            cv2.circle(disp, (int(cx*sx), int(cy*sy)), 6, color, -1)
        cy_norm = (kf.position[1] / H) if kf else 0.0
        cov = kf.covariance_trace if kf else 0.0
        speed = kf.speed if kf else 0.0
        cv2.rectangle(disp, (0, 0), (DW, 96), (0, 0, 0), -1)
        cv2.putText(disp, sm.state, (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 2)
        cv2.putText(disp, f"cy={cy_norm:.2f} (floor>={FLOOR_FRAC})  speed={speed:5.0f} "
                    f"(still<{SPEED_STILL_THRESHOLD:.0f})  cov={cov:6.0f}  {sm.current_sample_hz:.2f}Hz",
                    (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if sm.state == "FALL_SUSPECTED":
            cv2.putText(disp, "FALL SUSPECTED", (60, DH // 2), cv2.FONT_HERSHEY_SIMPLEX,
                        1.6, (0, 0, 255), 4)
        ok, buf = cv2.imencode(".jpg", disp, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with _lock:
                _latest["jpeg"] = buf.tobytes()


PAGE = b"""<!doctype html><html><head><title>Constant debug</title>
<style>body{background:#111;color:#eee;font-family:sans-serif;text-align:center;margin:0}
img{max-width:100%}</style></head><body><h3>Constant - live debug (dev tool)</h3>
<img src="/stream"></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    with _lock:
                        jpeg = _latest["jpeg"]
                    if jpeg:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg + b"\r\n")
                    time.sleep(1 / 15)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(PAGE)


if __name__ == "__main__":
    threading.Thread(target=capture_loop, daemon=True).start()
    print(f"[debug_view] http://<pi-ip>:{PORT}  (or tunnel: ssh -L {PORT}:localhost:{PORT})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
