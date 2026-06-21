"""Shared foreground-blob detector for the offline tools (recorder + analyzer).

Mirrors device/perception.py (single largest blob, MOG2 + open + dilate) but is
RESOLUTION-AWARE: the area bounds and dilate strength scale with the frame size, so
the exact same detection behaves comparably at 320x240 or 640x480. That lets us A/B
test capture resolution fairly instead of accidentally re-tuning area filters.

Production perception.py stays fixed at 320x240; this is experiment tooling.
"""
import cv2
import numpy as np

from device.perception import MIN_CONTOUR_AREA, MAX_CONTOUR_AREA  # 320x240 reference

REF_AREA = 320 * 240
REF_MIN_DIM = 240


def make_bg():
    return cv2.createBackgroundSubtractorMOG2(detectShadows=False)


def detect_blob(frame, fgbg):
    """Single largest foreground blob. Returns (x, y, w, h, cx, cy, aspect) or None."""
    h, w = frame.shape[:2]
    area_scale = (w * h) / REF_AREA
    lo, hi = MIN_CONTOUR_AREA * area_scale, MAX_CONTOUR_AREA * area_scale
    iters = max(1, round(2 * (min(w, h) / REF_MIN_DIM)))  # dilate scales with resolution

    mask = fgbg.apply(frame)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.dilate(mask, kernel, iterations=iters)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in contours if lo <= cv2.contourArea(c) <= hi]
    if not valid:
        return None
    largest = max(valid, key=cv2.contourArea)
    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None
    cx, cy = M["m10"] / M["m00"], M["m01"] / M["m00"]
    x, y, bw, bh = cv2.boundingRect(largest)
    return (x, y, bw, bh, cx, cy, bw / bh if bh > 0 else 1.0)
