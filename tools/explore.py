"""Feature exploration for fall detection — dump RICH features per clip so we can see
what actually separates falls from non-falls (beyond peak-vy / max-aspect).

For each clip, using the Kalman position (which holds through occlusion when MOG2
absorbs a still body), compute:
  vy_pk     peak downward velocity (px/s, normalized by frame height -> frac/s)
  cy_top    highest the centroid got (normalized 0=top..1=bottom)  -> standing height
  cy_end    centroid over the last ~1.5s (normalized)              -> where they ended
  drop      cy_end - cy_top                                        -> how far they went down
  end_still mean speed over last ~1.5s (frac/s)                    -> did they stop
  asp_end   aspect over last ~1.5s
  fg_bad    # frames rejected as whole-frame foreground

Idea under test: a FALL = large downward drop that ENDS low in the frame AND still;
a sit ends mid-frame, a crouch returns up, walking stays high and moving.

Usage (on the Pi):  python3 tools/explore.py *.mp4
"""
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from device.kalman import KalmanFilter
from blob import make_bg, detect_blob

TAIL_S = 1.5  # window at the end of the clip we call "where they ended up"


def category(path):
    b = os.path.basename(path)
    return "FALL" if b.startswith("fall") else "neg "


def explore(path):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 240
    dt = 1.0 / fps
    fgbg = make_bg()
    kf = None
    fg_bad = 0
    rows = []  # (cy_norm, speed_norm, aspect, has_det)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        # distinguish "whole-frame reject" from "simply no blob" for the fg_bad count
        m = fgbg.apply(frame.copy())
        if cv2.countNonZero(m) > 0.55 * frame.shape[0] * frame.shape[1]:
            fg_bad += 1
        det = detect_blob(frame, fgbg)
        if det is not None:
            cx, cy, aspect = det[4], det[5], det[6]
            if kf is None:
                kf = KalmanFilter(cx, cy)
            kf.predict(dt)
            kf.update(cx, cy)
            last_aspect = aspect
        elif kf is not None:
            kf.predict(dt)
        if kf is not None:
            rows.append((kf.position[1] / H, kf.speed / H, locals().get("last_aspect", 0.0)))
    cap.release()
    if not rows:
        return (os.path.basename(path), None)

    cy = np.array([r[0] for r in rows])
    sp = np.array([r[1] for r in rows])
    asp = np.array([r[2] for r in rows])
    tail = max(1, int(TAIL_S * fps))
    vy_pk = float(np.max(np.diff(cy)) / dt) if len(cy) > 1 else 0.0  # downward = +cy
    cy_top = float(cy.min())
    cy_end = float(cy[-tail:].mean())
    drop = cy_end - cy_top
    end_still = float(sp[-tail:].mean())
    asp_end = float(asp[-tail:].mean())
    return (os.path.basename(path),
            dict(vy_pk=vy_pk, cy_top=cy_top, cy_end=cy_end, drop=drop,
                 end_still=end_still, asp_end=asp_end, fg_bad=fg_bad))


if __name__ == "__main__":
    print(f"{'clip':>18} {'cat':>4} | {'vy_pk':>6} {'cy_top':>6} {'cy_end':>6} "
          f"{'drop':>6} {'end_still':>9} {'asp_end':>7} {'fg_bad':>6}")
    print("-" * 92)
    for p in sys.argv[1:]:
        name, f = explore(p)
        cat = category(p)
        if f is None:
            print(f"{name:>18} {cat:>4} | (no detection)")
            continue
        print(f"{name:>18} {cat:>4} | {f['vy_pk']:6.2f} {f['cy_top']:6.2f} {f['cy_end']:6.2f} "
              f"{f['drop']:6.2f} {f['end_still']:9.3f} {f['asp_end']:7.2f} {f['fg_bad']:6d}")
