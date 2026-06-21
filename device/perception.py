import time
import cv2
import numpy as np
from dataclasses import dataclass


MIN_CONTOUR_AREA = 500  # pixels — filters out noise and small objects


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
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 15)

    fgbg = cv2.createBackgroundSubtractorMOG2(detectShadows=False)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            mask = fgbg.apply(frame)
            frame = None  # release immediately — privacy enforcement point

            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if not contours:
                yield None
                continue

            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)

            if area < MIN_CONTOUR_AREA:
                yield None
                continue

            M = cv2.moments(largest)
            if M["m00"] == 0:
                yield None
                continue

            cx = M["m10"] / M["m00"]
            cy = M["m01"] / M["m00"]

            _, _, w, h = cv2.boundingRect(largest)
            aspect_ratio = w / h if h > 0 else 1.0

            yield Detection(cx=cx, cy=cy, area=area, aspect_ratio=aspect_ratio, timestamp=time.time())

    finally:
        cap.release()
