import time
import cv2
import numpy as np
from dataclasses import dataclass


MIN_CONTOUR_AREA = 500   # pixels — filters out noise and small objects
MAX_CONTOUR_AREA = 50000 # pixels — filters out large shadows / whole-frame noise
MERGE_DISTANCE   = 40    # pixels — contours closer than this are merged into one box


@dataclass
class Detection:
    cx: float          # centroid x
    cy: float          # centroid y
    area: float        # contour area in pixels
    aspect_ratio: float  # bbox width/height — tall/narrow when standing, wide/flat when fallen
    timestamp: float


def detections(source: int | str = 0):
    """
    Generator. Yields Detection on each frame where a foreground object is found,
    None on frames with no detection.

    source: 0 for webcam, path string for video file or image.
    """
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video source: {source}")

    # Pi-friendly resolution and frame rate
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
    cap.set(cv2.CAP_PROP_FPS, 10)

    fgbg = cv2.createBackgroundSubtractorMOG2(detectShadows=False)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            mask = fgbg.apply(frame)
            frame = None  # release immediately — privacy enforcement point

            # Open removes small noise; dilate merges nearby blobs into one person-blob
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.dilate(mask, kernel, iterations=2)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if not contours:
                yield None
                continue

            # Filter by area bounds — removes noise blobs and large shadow artifacts
            valid = [c for c in contours
                     if MIN_CONTOUR_AREA <= cv2.contourArea(c) <= MAX_CONTOUR_AREA]

            if not valid:
                yield None
                continue

            # Merge all valid contours into one bounding box — handles person split into blobs
            bboxes = [cv2.boundingRect(c) for c in valid]
            x = min(b[0] for b in bboxes)
            y = min(b[1] for b in bboxes)
            x2 = max(b[0] + b[2] for b in bboxes)
            y2 = max(b[1] + b[3] for b in bboxes)
            w = x2 - x
            h = y2 - y

            cx = x + w / 2
            cy = y + h / 2
            area = sum(cv2.contourArea(c) for c in valid)
            aspect_ratio = w / h if h > 0 else 1.0

            yield Detection(cx=cx, cy=cy, area=area, aspect_ratio=aspect_ratio, timestamp=time.time())

    finally:
        cap.release()
