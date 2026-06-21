"""Local touchscreen debug feed — see exactly what the pipeline sees.

  >>> DEV TOOL. Renders frames to the Pi's attached display; not the privacy path.

Shows the live camera (production 320x240 pipeline) on the touchscreen with the
detection box, centroid, the FLOOR line (fall threshold), state, and cy — so you can
check framing (are you fully in frame? does a fall cross the floor line?).

Owns the camera, so STOP monitoring_loop first:
    pkill -f monitoring_loop
    DISPLAY=:0 python3 tools/show_feed.py        # press q to quit
"""
import os
import sys
import time

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from device.kalman import KalmanFilter, LOW_COV, HIGH_COV
from device.state_machine import StateMachine, FLOOR_FRAC, SPEED_STILL_THRESHOLD
from blob import make_bg, detect_blob

W, H = 320, 240          # production resolution
DW, DH = 800, 480        # 7" touchscreen size
COLORS = {
    "PRESENT_NORMAL": (0, 200, 0), "PRESENT_STILL": (0, 200, 0),
    "UNCERTAIN": (0, 180, 255), "ABSENT": (150, 150, 150),
    "FALL_SUSPECTED": (0, 0, 255),
}


def main():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    if not cap.isOpened():
        print("could not open camera — is monitoring_loop still running? (pkill -f monitoring_loop)")
        return
    fgbg = make_bg()
    kf = None
    sm = StateMachine(emit_fn=lambda e: None, frame_h=H)
    last = None
    floor_y = int(FLOOR_FRAC * DH)

    win = "Constant feed"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    print("[show_feed] live on the touchscreen — press q to quit")

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
        cv2.line(disp, (0, floor_y), (DW, floor_y), (80, 80, 255), 2)
        cv2.putText(disp, "floor", (8, floor_y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 255), 1)
        if det is not None:
            x, y, w, h, cx, cy, _ = det
            sx, sy = DW / W, DH / H
            cv2.rectangle(disp, (int(x*sx), int(y*sy)), (int((x+w)*sx), int((y+h)*sy)), color, 2)
            cv2.circle(disp, (int(cx*sx), int(cy*sy)), 6, color, -1)
        else:
            cv2.putText(disp, "NO DETECTION (out of frame / too small)", (40, DH//2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 180, 255), 2)
        cy_norm = (kf.position[1] / H) if kf else 0.0
        cv2.rectangle(disp, (0, 0), (DW, 64), (0, 0, 0), -1)
        cv2.putText(disp, sm.state, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        cv2.putText(disp, f"cy={cy_norm:.2f} (floor>={FLOOR_FRAC})  speed={(kf.speed if kf else 0):4.0f}",
                    (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1)
        cv2.imshow(win, disp)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
