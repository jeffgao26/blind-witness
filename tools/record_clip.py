"""Guided clip recorder — live preview + bounding box + timed directive on the Pi
touchscreen while recording, with a BATCH mode that runs all takes back-to-back.

Opens the camera ONCE, so preview + detection overlay + cue + record happen
together. The on-screen bounding box / aspect readout / directive are drawn only on
the displayed copy — the saved files are the RAW scaled frame at the production
resolution (320x240 @10fps), so the analyzer sees exactly what the pipeline would.

The live box turns RED when aspect crosses the fall threshold, so you can watch the
tall->wide flip happen as you go down.

Run over SSH so it renders on the touchscreen:
    cd ~/blind-witness
    DISPLAY=:0 python3 tools/record_clip.py            # full batch (all takes)
    DISPLAY=:0 python3 tools/record_clip.py fall1.mp4 fall   # single take
Press q to abort.
"""
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from device.perception import MIN_CONTOUR_AREA, MAX_CONTOUR_AREA
from device.state_machine import ASPECT_FALL_THRESHOLD

OUT_W, OUT_H, FPS = 320, 240, 10
DW, DH = 960, 720       # display size on the touchscreen

# --- timeline (seconds) — tweak these if you want more/less time ---
OUT_PHASE = 3.0         # stay out of frame (background learning)
WALKIN_END = 7.0        # walk in + get set, until this time
ACTION_T = 11.0         # the moment to act (countdown runs WALKIN_END -> ACTION_T)
REC_ACTION = 16.0       # total record length for an action take
REC_MOVE = 14.0         # record length for the moving/baseline take
INTERMISSION = 6.0      # seconds between takes to reset

# (basename, mode, verb). mode "move" = keep moving; "action" = ready->countdown->DO->hold.
# Filenames get a run number suffix so you can collect multiple rounds (walk2.mp4, ...).
BASE_TAKES = [
    ("walk",        "move",   None),
    ("sit",         "action", "SIT DOWN"),
    ("crouch",      "action", "CROUCH DOWN"),
    ("couch",       "action", "LIE DOWN SLOWLY"),
    ("fall_side",   "action", "FALL SIDEWAYS"),
    ("fall_toward", "action", "FALL TOWARD CAM"),
    ("fall_down",   "action", "COLLAPSE DOWN"),
]


def takes_for_run(run: str):
    return [(f"{base}{run}.mp4", mode, verb) for base, mode, verb in BASE_TAKES]


def open_writer(path):
    for fourcc, suffix in (("mp4v", ".mp4"), ("XVID", ".avi")):
        p = path if path.endswith(suffix) else path.rsplit(".", 1)[0] + suffix
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*fourcc), FPS, (OUT_W, OUT_H))
        if w.isOpened():
            return w, p
    raise RuntimeError("could not open any VideoWriter codec")


def detect(small, fgbg):
    """Mirror of device/perception.py detection (single largest blob). 320x240 in.
    Returns (x, y, w, h, cx, cy, aspect) or None. For the live overlay only."""
    mask = fgbg.apply(small)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.dilate(mask, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in contours
             if MIN_CONTOUR_AREA <= cv2.contourArea(c) <= MAX_CONTOUR_AREA]
    if not valid:
        return None
    largest = max(valid, key=cv2.contourArea)
    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None
    cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
    x, y, w, h = cv2.boundingRect(largest)
    return (x, y, w, h, cx, cy, w / h if h > 0 else 1.0)


def directive(mode, verb, t, rec_dur):
    if t < OUT_PHASE:
        return "STAY OUT OF FRAME", "learning the empty room...", (0, 180, 255)
    if mode == "move":
        if t < rec_dur - 0.5:
            return "MOVE AROUND NORMALLY", "walk, turn, wave", (0, 220, 0)
        return "DONE", "", (200, 200, 200)
    if t < WALKIN_END:
        return "WALK INTO FRAME", "stand up straight, get set", (0, 220, 0)
    if t < ACTION_T:
        return f"GET READY: {verb}", f"{int(ACTION_T - t) + 1}", (0, 220, 0)
    if t < ACTION_T + 1.3:
        return f"{verb} NOW!", "", (0, 0, 255)
    if t < rec_dur - 0.3:
        return "HOLD STILL - DON'T MOVE", "", (0, 0, 255)
    return "DONE", "", (200, 200, 200)


def show(win, frame, big, sub, color, rem, det=None):
    disp = cv2.flip(cv2.resize(frame, (DW, DH)), 1)  # mirror for a natural preview
    if det is not None:
        x, y, w, h, cx, cy, aspect = det
        sx, sy = DW / OUT_W, DH / OUT_H
        rw, rh = w * sx, h * sy
        fx = DW - (x * sx + rw)            # flip x to match the mirrored image
        fcx = DW - cx * sx
        boxcol = (0, 0, 255) if aspect > ASPECT_FALL_THRESHOLD else (0, 220, 0)
        cv2.rectangle(disp, (int(fx), int(y * sy)), (int(fx + rw), int(y * sy + rh)), boxcol, 2)
        cv2.circle(disp, (int(fcx), int(cy * sy)), 6, boxcol, -1)
        cv2.putText(disp, f"aspect={aspect:.2f}", (int(fx), max(150, int(y * sy) - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, boxcol, 2)
    cv2.rectangle(disp, (0, 0), (DW, 130), (0, 0, 0), -1)
    cv2.putText(disp, big, (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3)
    if sub:
        size = 3.0 if sub.isdigit() else 0.9
        cv2.putText(disp, sub, (20, 112), cv2.FONT_HERSHEY_SIMPLEX, size, color, 3)
    cv2.putText(disp, f"{rem:4.1f}s", (840, 700), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (255, 255, 255), 2)
    cv2.imshow(win, disp)
    return cv2.waitKey(1) & 0xFF


def pace(loop_start):
    time.sleep(max(0.0, 1.0 / FPS - (time.time() - loop_start)))


def intermission(cap, win, next_label):
    fgbg = cv2.createBackgroundSubtractorMOG2(detectShadows=False)
    t0 = time.time()
    while time.time() - t0 < INTERMISSION:
        ls = time.time()
        ret, frame = cap.read()
        if not ret:
            continue
        det = detect(cv2.resize(frame, (OUT_W, OUT_H)), fgbg)
        if show(win, frame, "NEXT: " + next_label, "step OUT of frame",
                (255, 200, 0), INTERMISSION - (ls - t0), det) == ord("q"):
            return False
        pace(ls)
    return True


def record_take(cap, win, out_path, mode, verb):
    writer, real_path = open_writer(out_path)
    fgbg = cv2.createBackgroundSubtractorMOG2(detectShadows=False)
    rec_dur = REC_MOVE if mode == "move" else REC_ACTION
    t0 = time.time()
    n = 0
    aborted = False
    while time.time() - t0 < rec_dur:
        ls = time.time()
        t = ls - t0
        ret, frame = cap.read()
        if not ret:
            continue
        small = cv2.resize(frame, (OUT_W, OUT_H))
        writer.write(small)                 # raw, no overlay
        n += 1
        det = detect(small, fgbg)
        big, sub, color = directive(mode, verb, t, rec_dur)
        if show(win, frame, big, sub, color, rec_dur - t, det) == ord("q"):
            aborted = True
            break
        pace(ls)
    writer.release()
    print(f"[record] wrote {real_path} ({n} frames)")
    return not aborted


def main(takes):
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cap.isOpened():
        print("could not open camera"); return
    win = "Constant recorder"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    print(f"[record] batch of {len(takes)} takes — watch the touchscreen")
    try:
        for idx, (fname, mode, verb) in enumerate(takes):
            label = verb if verb else "WALK / MOVE"
            if idx > 0 and not intermission(cap, win, label):
                break
            print(f"[record] take {idx + 1}/{len(takes)}: {fname} ({label})")
            if not record_take(cap, win, fname, mode, verb):
                print("[record] aborted"); break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    print("[record] done. Analyze with:\n  python3 tools/analyze_clip.py " +
          " ".join(t[0] for t in takes))


if __name__ == "__main__":
    # Usage:
    #   record_clip.py                -> batch, run 1  (walk1.mp4, sit1.mp4, ...)
    #   record_clip.py 2              -> batch, run 2  (walk2.mp4, sit2.mp4, ...)
    #   record_clip.py fall1.mp4 fall -> single take
    args = sys.argv[1:]
    if len(args) >= 2 and not args[0].isdigit():
        verb = None if args[1] == "walk" else args[1].upper()
        mode = "move" if args[1] == "walk" else "action"
        main([(args[0], mode, verb)])
    else:
        run = args[0] if args and args[0].isdigit() else "1"
        main(takes_for_run(run))
