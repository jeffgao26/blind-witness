"""DEBUG / DEMO viewer — streams the annotated camera feed to a browser.

  >>> DEV TOOL ONLY. This deliberately retains and transmits video frames. It is
  >>> NOT part of the privacy-guaranteed monitoring path (device/monitoring_loop.py
  >>> still never touches storage or the network with a frame). This is the PRD's
  >>> "debug/demo view" — for tuning and for showing judges the mechanism.

Runs the REAL device estimation (device.kalman.KalmanFilter) and the REAL state
machine (device.state_machine.StateMachine) so what you see on screen is exactly
what the production loop computes. Only the capture + MOG2 extraction is mirrored
here (perception.detect() intentionally won't hand back a frame).

Run on the Pi:
    cd ~/blind-witness && python3 tools/debug_view.py
Then on your laptop browser:
    http://<pi-ip>:8080
"""
import os
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device.kalman import KalmanFilter, LOW_COV, HIGH_COV
from device.state_machine import StateMachine
from device.perception import MIN_CONTOUR_AREA  # keep detection params in sync

PORT = 8080
W, H, FPS = 640, 480, 15

# state colors (BGR)
COLORS = {
    "PRESENT_NORMAL": (0, 200, 0),
    "PRESENT_STILL":  (0, 200, 0),
    "UNCERTAIN":      (0, 180, 255),
    "ABSENT":         (150, 150, 150),
    "FALL_SUSPECTED": (0, 0, 255),
}

_latest = {"jpeg": None}
_lock = threading.Lock()


def capture_loop():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    fgbg = cv2.createBackgroundSubtractorMOG2(detectShadows=False)

    kf = None
    sm = StateMachine(emit_fn=lambda e: None, source="live")  # state only; no Redis here
    last = None

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        # --- detection (mirror of perception.detect) ---
        mask = fgbg.apply(frame)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        det = None      # (cx, cy, area, aspect)
        bbox = None
        if contours:
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            if area >= MIN_CONTOUR_AREA:
                M = cv2.moments(largest)
                if M["m00"] != 0:
                    cx = M["m10"] / M["m00"]
                    cy = M["m01"] / M["m00"]
                    x, y, w, h = cv2.boundingRect(largest)
                    aspect = w / h if h > 0 else 1.0
                    det = (cx, cy, area, aspect)
                    bbox = (x, y, w, h)

        # --- real estimation + state ---
        now = time.time()
        dt = (now - last) if last is not None else 1.0 / FPS
        last = now

        class _D:  # minimal Detection stand-in for the state machine
            pass
        d_obj = None
        if det is not None:
            cx, cy, area, aspect = det
            if kf is None:
                kf = KalmanFilter(cx, cy)
            kf.predict(dt)
            kf.update(cx, cy)
            d_obj = _D()
            d_obj.cx, d_obj.cy, d_obj.area, d_obj.aspect_ratio = cx, cy, area, aspect
            d_obj.timestamp = now
        elif kf is not None:
            kf.predict(dt)
        if kf is not None:
            sm.update(kf, d_obj)

        # --- overlay ---
        color = COLORS.get(sm.state, (255, 255, 255))
        if bbox is not None:
            x, y, w, h = bbox
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        if det is not None:
            cx, cy, _, _ = det
            cv2.circle(frame, (int(cx), int(cy)), 5, color, -1)
        if kf is not None:
            px, py = kf.position
            cv2.drawMarker(frame, (int(px), int(py)), (255, 255, 0),
                           cv2.MARKER_CROSS, 16, 2)

        cov = kf.covariance_trace if kf else 0.0
        vy = kf.vy if kf else 0.0
        speed = kf.speed if kf else 0.0
        aspect = det[3] if det else 0.0
        fall_armed = sm._fall_candidate_at is not None

        cv2.rectangle(frame, (0, 0), (W, 96), (0, 0, 0), -1)
        cv2.putText(frame, sm.state, (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
        line2 = f"cov={cov:7.1f} ({'CONF' if cov < LOW_COV else 'UNC' if cov > HIGH_COV else 'mid'})  rate={sm.current_sample_hz:.2f}Hz"
        cv2.putText(frame, line2, (10, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        line3 = f"vy={vy:7.1f}px/s  speed={speed:6.1f}  aspect={aspect:.2f}  fall_armed={fall_armed}"
        cv2.putText(frame, line3, (10, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if sm.state == "FALL_SUSPECTED":
            cv2.putText(frame, "FALL SUSPECTED", (60, H // 2), cv2.FONT_HERSHEY_SIMPLEX,
                        1.6, (0, 0, 255), 4)

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with _lock:
                _latest["jpeg"] = buf.tobytes()


PAGE = b"""<!doctype html><html><head><title>Constant - debug view</title>
<style>body{background:#111;color:#eee;font-family:sans-serif;text-align:center;margin:0}
img{max-width:100%;height:auto}h3{margin:8px}</style></head>
<body><h3>Constant - live debug (dev tool, not the product path)</h3>
<img src="/stream"></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    with _lock:
                        jpeg = _latest["jpeg"]
                    if jpeg is None:
                        time.sleep(0.05)
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                    time.sleep(1.0 / FPS)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE)


if __name__ == "__main__":
    threading.Thread(target=capture_loop, daemon=True).start()
    print(f"[debug_view] open http://<pi-ip>:{PORT} on your laptop browser (Ctrl-C to stop)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
