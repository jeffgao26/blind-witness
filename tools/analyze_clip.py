"""Offline fall-detection tuner — run the real estimator over a recorded clip.

Uses tools/blob.py (resolution-scaled detection) + device.kalman.KalmanFilter.
Deterministic (dt from clip FPS, no wall clock) so it's repeatable. Works at any
clip resolution — area thresholds scale with frame size — so you can compare a
320x240 collection against a 640x480 one fairly.

Prints the per-frame signal trace and a summary: peak downward vy and the aspect at
that moment (the two numbers that set VY_FALL_THRESHOLD / ASPECT_FALL_THRESHOLD),
plus whether the current thresholds would fire FALL_SUSPECTED.

Usage (on the Pi):
    cd ~/blind-witness && python3 tools/analyze_clip.py fall1.mp4 sit1.mp4 ...
"""
import os
import sys

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # repo root (device.*)
sys.path.insert(0, HERE)                     # tools/ (blob)
from device.kalman import KalmanFilter, LOW_COV, HIGH_COV
from device.state_machine import (
    VY_FALL_THRESHOLD, ASPECT_FALL_THRESHOLD,
    FALL_CONFIRM_SECONDS, SPEED_STILL_THRESHOLD,
)
from blob import make_bg, detect_blob


def analyze(path: str):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print(f"could not open {path}\n")
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    dt = 1.0 / fps
    confirm_frames = int(FALL_CONFIRM_SECONDS * fps)
    fgbg = make_bg()

    print(f"clip={path}  {w}x{h} @ {fps:.1f}fps  confirm_frames={confirm_frames}")
    print(f"thresholds: VY>{VY_FALL_THRESHOLD} px/s  ASPECT>{ASPECT_FALL_THRESHOLD}  "
          f"STILL<{SPEED_STILL_THRESHOLD} px/s  CONFIRM={FALL_CONFIRM_SECONDS}s")
    print(f"{'t(s)':>6} {'det':>3} {'vy':>8} {'speed':>7} {'aspect':>6} {'cov':>8}  notes")

    kf = None
    i = 0
    peak_vy = 0.0
    aspect_at_peak = 0.0
    max_aspect = 0.0
    candidate_idx = None
    still_streak = 0
    fired_at = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        det = detect_blob(frame, fgbg)
        has_det = det is not None
        if has_det:
            cx, cy, aspect = det[4], det[5], det[6]
            if kf is None:
                kf = KalmanFilter(cx, cy)
            kf.predict(dt)
            kf.update(cx, cy)
        else:
            aspect = None
            if kf is not None:
                kf.predict(dt)

        vy = kf.vy if kf else 0.0
        speed = kf.speed if kf else 0.0
        cov = kf.covariance_trace if kf else 0.0

        if vy > peak_vy:
            peak_vy, aspect_at_peak = vy, (aspect or 0.0)
        if aspect and aspect > max_aspect:
            max_aspect = aspect

        notes = ""
        if has_det and vy > VY_FALL_THRESHOLD and (aspect or 0) > ASPECT_FALL_THRESHOLD:
            if candidate_idx is None:
                candidate_idx = i
                notes = "FALL CANDIDATE armed"
        if candidate_idx is not None and has_det:
            still_streak = still_streak + 1 if speed < SPEED_STILL_THRESHOLD else 0
            if still_streak >= confirm_frames and fired_at is None:
                fired_at = i
                notes = ">>> FALL_SUSPECTED would fire"
        if not has_det:
            candidate_idx = None
            still_streak = 0

        if i % max(1, int(fps // 5)) == 0 or notes:
            print(f"{i/fps:6.2f} {('Y' if has_det else '-'):>3} {vy:8.1f} {speed:7.1f} "
                  f"{(aspect or 0):6.2f} {cov:8.1f}  {notes}")
        i += 1

    cap.release()
    print("\n--- SUMMARY ---")
    print(f"peak downward vy = {peak_vy:.1f} px/s   (aspect at that moment = {aspect_at_peak:.2f})")
    print(f"max aspect ratio = {max_aspect:.2f}")
    print(f"FALL_SUSPECTED fired: {'YES at t=%.2fs' % (fired_at / fps) if fired_at is not None else 'no'}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 tools/analyze_clip.py <clip.mp4> [more.mp4 ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(p)
