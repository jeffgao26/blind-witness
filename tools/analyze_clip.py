"""Offline fall-detection tuner — run the REAL pipeline over a recorded clip.

Uses the production perception (device.perception.detections) and the production
estimator (device.kalman.KalmanFilter) directly, so it never drifts from whatever
the perception code currently does. Deterministic (dt from clip FPS, no wall clock)
so it's repeatable: record a clip once, re-run while we tune thresholds.

IMPORTANT: thresholds are in PIXELS, so clips MUST be recorded at the production
resolution (currently 320x240) or the numbers won't transfer. The analyzer warns
if the clip resolution doesn't match.

Prints the per-frame signal trace and a summary: peak downward vy and the aspect at
that moment (the two numbers that set VY_FALL_THRESHOLD / ASPECT_FALL_THRESHOLD),
plus whether the current thresholds would fire FALL_SUSPECTED on this clip.

Usage (on the Pi, where the clips are):
    cd ~/blind-witness && python3 tools/analyze_clip.py fall1.mp4
    python3 tools/analyze_clip.py fall1.mp4 sit1.mp4 walk1.mp4
"""
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device.kalman import KalmanFilter, LOW_COV, HIGH_COV
from device.perception import detections
from device.state_machine import (
    VY_FALL_THRESHOLD, ASPECT_FALL_THRESHOLD,
    FALL_CONFIRM_SECONDS, SPEED_STILL_THRESHOLD,
)

PROD_RES = (320, 240)  # keep in sync with device/perception.py cap settings


def analyze(path: str):
    probe = cv2.VideoCapture(path)
    if not probe.isOpened():
        print(f"could not open {path}\n")
        return
    fps = probe.get(cv2.CAP_PROP_FPS) or 10.0
    w = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
    probe.release()

    dt = 1.0 / fps
    confirm_frames = int(FALL_CONFIRM_SECONDS * fps)

    print(f"clip={path}  {w}x{h} @ {fps:.1f}fps  confirm_frames={confirm_frames}")
    if (w, h) != PROD_RES:
        print(f"  !! WARNING: not production res {PROD_RES[0]}x{PROD_RES[1]} — pixel "
              f"thresholds (vy/aspect/area) won't transfer. Re-record at {PROD_RES[0]}x{PROD_RES[1]}.")
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

    for det in detections(path):   # the REAL perception, over the file
        has_det = det is not None
        if has_det:
            if kf is None:
                kf = KalmanFilter(det.cx, det.cy)
            kf.predict(dt)
            kf.update(det.cx, det.cy)
        elif kf is not None:
            kf.predict(dt)

        vy = kf.vy if kf else 0.0
        speed = kf.speed if kf else 0.0
        cov = kf.covariance_trace if kf else 0.0
        aspect = det.aspect_ratio if has_det else None

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

    print("\n--- SUMMARY ---")
    print(f"peak downward vy = {peak_vy:.1f} px/s   (aspect at that moment = {aspect_at_peak:.2f})")
    print(f"max aspect ratio = {max_aspect:.2f}")
    print(f"FALL_SUSPECTED fired: {'YES at t=%.2fs' % (fired_at / fps) if fired_at is not None else 'no'}")
    print("Tuning: set VY_FALL_THRESHOLD below a real fall's peak vy but above a sit-down's;")
    print("same idea for ASPECT_FALL_THRESHOLD (standing < 1.0, lying flat > ~1.5).\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 tools/analyze_clip.py <clip.mp4> [more.mp4 ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(p)
