"""Guided clip recorder — live preview + bounding box + timed directive on the Pi
touchscreen while recording, with BATCH mode (all takes back-to-back) and a
selectable capture resolution for A/B testing.

Opens the camera ONCE: preview + detection overlay + cue + record together. The
on-screen box / aspect readout / directive are drawn only on the displayed copy —
saved files are the RAW frame at the chosen resolution. The live box turns RED when
aspect crosses the fall threshold, so you can watch the tall->wide flip.

Run over SSH so it renders on the touchscreen:
    cd ~/blind-witness
    DISPLAY=:0 python3 tools/record_clip.py              # batch run 1, SD (320x240)
    DISPLAY=:0 python3 tools/record_clip.py 2 hd         # batch run 2, HD (640x480)
    DISPLAY=:0 python3 tools/record_clip.py fall1.mp4 fall   # single take
Press q to abort.
"""
import os
import subprocess
import sys
import time

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # repo root (device.*)
sys.path.insert(0, HERE)                     # tools/ (blob)
from device.state_machine import ASPECT_FALL_THRESHOLD
from blob import make_bg, detect_blob

FPS = 10
DW, DH = 960, 720       # display size on the touchscreen
OUT_W, OUT_H = 320, 240  # capture/save resolution (set from CLI)
RESOLUTIONS = {"sd": (320, 240), "hd": (640, 480)}

# --- timeline (seconds) — tweak if you want more/less time ---
OUT_PHASE = 3.0         # stay out of frame (background learning)
WALKIN_END = 7.0        # walk in + get set, until this time
ACTION_T = 11.0         # the moment to act (countdown runs WALKIN_END -> ACTION_T)
REC_ACTION = 16.0       # total record length for an action take
REC_MOVE = 14.0         # record length for the moving/baseline take
INTERMISSION = 6.0      # seconds between takes to reset

# (basename, mode, verb). mode "move" = keep moving; "action" = ready->countdown->DO->hold.
BASE_TAKES = [
    ("walk",        "move",   None),
    ("sit",         "action", "SIT DOWN"),
    ("crouch",      "action", "CROUCH DOWN"),
    ("couch",       "action", "LIE DOWN SLOWLY"),
    ("fall_side",   "action", "FALL SIDEWAYS"),
    ("fall_toward", "action", "FALL TOWARD CAM"),
    ("fall_down",   "action", "COLLAPSE DOWN"),
]


def takes_for_run(run):
    return [(f"{base}{run}.mp4", mode, verb) for base, mode, verb in BASE_TAKES]


def _get_ctrl(dev, name):
    try:
        out = subprocess.run(["v4l2-ctl", "-d", dev, f"--get-ctrl={name}"],
                             capture_output=True, text=True).stdout
        return int(out.split(":")[1])
    except Exception:
        return None


def lock_camera(dev="/dev/video0"):
    """Freeze exposure / white-balance / focus so global lighting shifts stop
    fooling MOG2 into whole-frame 'motion'. Locks to whatever auto just chose, so
    brightness stays correct for the room. No-op if v4l2-ctl is missing."""
    if not subprocess.run(["which", "v4l2-ctl"], capture_output=True).returncode == 0:
        print("[record] v4l2-ctl missing — auto-exposure NOT locked (sudo apt install v4l-utils)")
        return
    exp = _get_ctrl(dev, "exposure_time_absolute") or 333
    gain = _get_ctrl(dev, "gain") or 128
    wb = _get_ctrl(dev, "white_balance_temperature") or 4000
    foc = _get_ctrl(dev, "focus_absolute") or 35
    ctrls = [
        "auto_exposure=1",                    # manual
        f"exposure_time_absolute={exp}",
        "exposure_dynamic_framerate=0",
        f"gain={gain}",
        "white_balance_automatic=0",
        f"white_balance_temperature={wb}",
        "focus_automatic_continuous=0",
        f"focus_absolute={foc}",
    ]
    subprocess.run(["v4l2-ctl", "-d", dev, *[f"--set-ctrl={c}" for c in ctrls]],
                   capture_output=True)
    print(f"[record] camera LOCKED: exposure={exp} gain={gain} wb={wb} focus={foc}")


def open_writer(path):
    for fourcc, suffix in (("mp4v", ".mp4"), ("XVID", ".avi")):
        p = path if path.endswith(suffix) else path.rsplit(".", 1)[0] + suffix
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*fourcc), FPS, (OUT_W, OUT_H))
        if w.isOpened():
            return w, p
    raise RuntimeError("could not open any VideoWriter codec")


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
    fgbg = make_bg()
    t0 = time.time()
    while time.time() - t0 < INTERMISSION:
        ls = time.time()
        ret, frame = cap.read()
        if not ret:
            continue
        det = detect_blob(cv2.resize(frame, (OUT_W, OUT_H)), fgbg)
        if show(win, frame, "NEXT: " + next_label, "step OUT of frame",
                (255, 200, 0), INTERMISSION - (ls - t0), det) == ord("q"):
            return False
        pace(ls)
    return True


def record_take(cap, win, out_path, mode, verb):
    writer, real_path = open_writer(out_path)
    fgbg = make_bg()
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
        det = detect_blob(small, fgbg)
        big, sub, color = directive(mode, verb, t, rec_dur)
        if show(win, frame, big, sub, color, rec_dur - t, det) == ord("q"):
            aborted = True
            break
        pace(ls)
    writer.release()
    print(f"[record] wrote {real_path} ({n} frames, {OUT_W}x{OUT_H}, ~{n/rec_dur:.0f}fps actual)")
    return not aborted


def main(takes):
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, OUT_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, OUT_H)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    if not cap.isOpened():
        print("could not open camera"); return
    for _ in range(15):     # let auto-exposure/WB settle on the current room...
        cap.read()
    lock_camera()           # ...then freeze it so MOG2 isn't fooled by lighting drift
    win = "Constant recorder"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    print(f"[record] {len(takes)} takes @ {OUT_W}x{OUT_H} — watch the touchscreen")
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
    args = sys.argv[1:]
    # single take: <out.mp4> <verb>
    if args and (args[0].endswith(".mp4") or args[0].endswith(".avi")):
        verb = None if (len(args) > 1 and args[1] == "walk") else (args[1].upper() if len(args) > 1 else "FALL")
        mode = "move" if (len(args) > 1 and args[1] == "walk") else "action"
        main([(args[0], mode, verb)])
    else:
        run = "1"
        for a in args:
            if a.isdigit():
                run = a
            elif a in RESOLUTIONS:
                OUT_W, OUT_H = RESOLUTIONS[a]
            elif a.endswith("fps") and a[:-3].isdigit():
                FPS = int(a[:-3])          # e.g. "30fps" -> capture/record at 30fps
        main(takes_for_run(run))
