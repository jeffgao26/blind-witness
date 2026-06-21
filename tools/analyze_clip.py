"""Offline state-machine replay — run the REAL device pipeline over a recorded clip.

Drives blob.detect_blob -> KalmanFilter -> the actual StateMachine (with an injected
clock so wall-clock thresholds replay deterministically) and reports the state timeline
plus whether FALL_SUSPECTED fired. This tests the production logic, not a mirror of it.

Works at any clip resolution (blob scales area; StateMachine floor zone is set from the
clip height).

Usage (on the Pi):
    cd ~/blind-witness && python3 tools/analyze_clip.py fall_side4.mp4 sit4.mp4 ...
"""
import os
import sys

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from device.kalman import KalmanFilter
from device.state_machine import StateMachine
from blob import make_bg, detect_blob


def analyze(path: str):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print(f"could not open {path}\n")
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 240
    dt = 1.0 / fps
    fgbg = make_bg()

    events = []   # (t, state)
    sm = StateMachine(emit_fn=lambda e: events.append((e.timestamp, e.state)), frame_h=H)
    kf = None
    i = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        det = detect_blob(frame, fgbg)
        now = i * dt
        if det is not None:
            cx, cy = det[4], det[5]
            if kf is None:
                kf = KalmanFilter(cx, cy)
            kf.predict(dt)
            kf.update(cx, cy)
        elif kf is not None:
            kf.predict(dt)
        if kf is not None:
            sm.update(kf, det, now=now)
        i += 1
    cap.release()

    # collapse consecutive duplicate states into a timeline
    timeline = []
    for t, s in events:
        if not timeline or timeline[-1][1] != s:
            timeline.append((t, s))
    fired = next((t for t, s in events if s == "FALL_SUSPECTED"), None)
    seq = " -> ".join(f"{s}@{t:.1f}s" for t, s in timeline)
    verdict = f"FALL_SUSPECTED @ {fired:.1f}s" if fired is not None else "no fall"
    print(f"{os.path.basename(path):>18} | {verdict:>22} | {seq}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 tools/analyze_clip.py <clip.mp4> [more.mp4 ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(p)
