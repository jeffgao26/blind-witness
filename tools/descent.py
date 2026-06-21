"""Descent-rate test — does a fall drop faster than lying down?

Measures the SUSTAINED downward speed of the centroid, robust to single-frame
flicker (median-filter cy, then take the max of velocity smoothed over ~0.25s).
Reported in frame-heights/second. Hypothesis: falls > controlled lie-downs.

A global fps mislabel only rescales all clips equally, so the fall-vs-liedown
SEPARATION is preserved — record at 30fps for temporal resolution and don't worry
about exact timing.

Usage (on the Pi):  python3 tools/descent.py walk7.mp4 sit7.mp4 fall_side7.mp4 ...
"""
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from blob import make_bg, detect_blob


def category(path):
    return "FALL" if os.path.basename(path).startswith("fall") else "neg "


def descent(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 240
    fgbg = make_bg()
    ts, cys = [], []   # only frames with a detection (descent happens while moving)
    i = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        det = detect_blob(frame, fgbg)
        if det is not None:
            ts.append(i / fps)
            cys.append(det[5] / H)   # normalized cy (0=top, 1=floor)
        i += 1
    cap.release()
    if len(cys) < 5:
        return dict(rate=0.0, drop=0.0, cy_top=0.0, cy_floor=0.0)

    cy = np.array(cys)
    t = np.array(ts)
    # median filter (k=3) to kill single-frame blob flicker
    cym = cy.copy()
    for k in range(1, len(cy) - 1):
        cym[k] = np.median(cy[k - 1:k + 2])
    # per-step downward velocity, then moving-average over ~0.25s for a sustained rate
    v = np.diff(cym) / np.maximum(np.diff(t), 1e-3)
    win = max(1, int(0.25 * fps))
    if len(v) >= win:
        vs = np.convolve(v, np.ones(win) / win, mode="valid")
        rate = float(vs.max())          # fastest sustained downward rate (frame-heights/s)
    else:
        rate = float(v.max()) if len(v) else 0.0
    return dict(rate=rate, drop=float(cym.max() - cym.min()),
                cy_top=float(cym.min()), cy_floor=float(cym.max()))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 tools/descent.py <clip.mp4> [more.mp4 ...]")
        sys.exit(1)
    print(f"{'clip':>18} {'cat':>4} | {'descent_rate':>12} {'drop':>6} {'cy_top':>6} {'cy_floor':>8}")
    print("-" * 70)
    for p in sys.argv[1:]:
        f = descent(p)
        if f is None:
            print(f"{os.path.basename(p):>18} {category(p):>4} | (could not open)")
            continue
        print(f"{os.path.basename(p):>18} {category(p):>4} | {f['rate']:12.2f} "
              f"{f['drop']:6.2f} {f['cy_top']:6.2f} {f['cy_floor']:8.2f}")
