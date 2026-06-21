import time
import redis
from contracts.events import STREAM
from device.perception import detections
from device.kalman import KalmanFilter
from device.state_machine import StateMachine

REDIS_HOST = "localhost"
REDIS_PORT = 6379

VIDEO_SOURCE = 0  # 0 = webcam, or path to video file for testing

# Camera handoff coordination (plain redis flags; this module knows nothing about what
# takes the camera — deliberately no reference to the emergency path, so the privacy
# boundary holds: grep -ri emergency device/ stays clean).
YIELD_KEY    = "eldercare:camera_yield"     # set externally -> release the camera and pause
RELEASED_KEY = "eldercare:camera_released"  # we set this once the camera is actually free


def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    def emit(event):
        entry = event.to_redis()
        entry["covariance_trace"] = str(kf.covariance_trace)
        r.xadd(STREAM, entry)

    sm = StateMachine(emit_fn=emit, source="live")

    # Outer loop lets us release and later re-acquire the camera.
    while True:
        if r.get(YIELD_KEY):
            r.set(RELEASED_KEY, "1")
            print("[device] camera yielded — monitoring paused")
            while r.get(YIELD_KEY):
                time.sleep(0.5)
            r.delete(RELEASED_KEY)
            print("[device] camera reacquired — monitoring resumed")

        kf = None
        last_time = None
        gen = detections(VIDEO_SOURCE)   # opens the camera
        try:
            for detection in gen:
                now = time.time()
                dt = (now - last_time) if last_time is not None else 0.033
                last_time = now

                if detection is not None:
                    if kf is None:
                        kf = KalmanFilter(detection.cx, detection.cy)
                    kf.predict(dt)
                    kf.update(detection.cx, detection.cy)
                elif kf is not None:
                    kf.predict(dt)

                if kf is not None:
                    sm.update(kf, detection)

                if r.get(YIELD_KEY):
                    break   # step aside; closing the generator releases the camera
        finally:
            gen.close()     # runs detections()'s finally -> cap.release()


if __name__ == "__main__":
    main()
