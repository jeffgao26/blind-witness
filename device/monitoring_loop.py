import time
import redis
from contracts.events import STREAM
from device.perception import detections
from device.kalman import KalmanFilter
from device.state_machine import StateMachine

REDIS_HOST = "localhost"
REDIS_PORT = 6379

VIDEO_SOURCE = 0  # 0 = webcam, or path to video file for testing


def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    def emit(event):
        entry = event.to_redis()
        entry["covariance_trace"] = str(kf.covariance_trace)
        r.xadd(STREAM, entry)

    sm = StateMachine(emit_fn=emit, source="live")
    kf = None
    last_time = None

    for detection in detections(VIDEO_SOURCE):
        now = time.time()
        dt = (now - last_time) if last_time is not None else 0.033
        last_time = now

        if detection is not None:
            if kf is None:
                kf = KalmanFilter(detection.cx, detection.cy)
            kf.predict(dt)
            kf.update(detection.cx, detection.cy)
        else:
            if kf is not None:
                kf.predict(dt)

        if kf is not None:
            sm.update(kf, detection)


if __name__ == "__main__":
    main()
