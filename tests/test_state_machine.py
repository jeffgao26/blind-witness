import time
import pytest
from unittest.mock import MagicMock
from device.kalman import KalmanFilter
from device.state_machine import (
    StateMachine,
    ASPECT_FALL_THRESHOLD,
    FALL_CONFIRM_SECONDS,
    SPEED_STILL_THRESHOLD,
    STILL_SECONDS,
    DEBOUNCE_SECONDS,
    ABSENCE_THRESHOLD,
    FLOOR_FRAC,
    FRAME_H,
)
from device.perception import Detection

FLOOR_Y = FLOOR_FRAC * FRAME_H   # centroid y >= this → "on the floor"


def make_detection(cx=100, cy=100, area=5000, aspect_ratio=0.4):
    return Detection(cx=cx, cy=cy, area=area, aspect_ratio=aspect_ratio, timestamp=time.time())


def make_kf(speed=50.0, vy=0.0, covariance_trace=20.0, cy=100.0):
    kf = MagicMock(spec=KalmanFilter)
    kf.speed = speed
    kf.vy = vy
    kf.covariance_trace = covariance_trace
    kf.position = (100.0, cy)   # (x, y); y drives floor detection
    kf.is_confident = covariance_trace < 200.0
    kf.is_uncertain = covariance_trace >= 200.0
    return kf


def make_kf_down(speed=None):
    """KF with centroid on the floor and still."""
    return make_kf(speed=SPEED_STILL_THRESHOLD - 1, cy=FLOOR_Y + 10)


def make_kf_upright(speed=100.0):
    """KF with centroid clearly above the floor zone."""
    return make_kf(speed=speed, cy=FLOOR_Y - 40)


def test_present_normal_when_moving(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    sm.update(make_kf_upright(speed=100.0), make_detection())
    monkeypatch.setattr(time, "time", lambda: now + DEBOUNCE_SECONDS + 0.1)
    sm.update(make_kf_upright(speed=100.0), make_detection())
    assert sm.state == "PRESENT_NORMAL"


def test_absent_after_absence_threshold(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + ABSENCE_THRESHOLD + 0.1)
    sm.update(make_kf(), None)
    monkeypatch.setattr(time, "time", lambda: now + ABSENCE_THRESHOLD + DEBOUNCE_SECONDS + 0.2)
    sm.update(make_kf(), None)
    assert sm.state == "ABSENT"


def test_uncertain_before_absence_threshold(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + ABSENCE_THRESHOLD - 0.5)
    sm.update(make_kf(), None)
    assert sm.state == "UNCERTAIN"


def test_fall_not_confirmed_before_window(monkeypatch):
    """Centroid on floor + still, but not yet held for FALL_CONFIRM_SECONDS."""
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    kf = make_kf_down()
    det = make_detection()
    monkeypatch.setattr(time, "time", lambda: now)
    sm.update(kf, det)
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS - 0.5)
    sm.update(kf, det)
    assert sm.state != "FALL_SUSPECTED"


def test_fall_confirmed_after_window(monkeypatch):
    """Centroid on floor + still, held for FALL_CONFIRM_SECONDS → FALL_SUSPECTED."""
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    kf = make_kf_down()
    det = make_detection()
    monkeypatch.setattr(time, "time", lambda: now)
    sm.update(kf, det)
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS + 0.1)
    sm.update(kf, det)
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS + DEBOUNCE_SECONDS + 0.2)
    sm.update(kf, det)
    assert sm.state == "FALL_SUSPECTED"


def test_fall_not_triggered_upright(monkeypatch):
    """Centroid above floor zone — should never reach FALL_SUSPECTED."""
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    kf = make_kf_upright(speed=SPEED_STILL_THRESHOLD - 1)  # still but upright
    det = make_detection()
    monkeypatch.setattr(time, "time", lambda: now)
    sm.update(kf, det)
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS + DEBOUNCE_SECONDS + 1)
    sm.update(kf, det)
    assert sm.state != "FALL_SUSPECTED"


def test_fall_not_triggered_moving(monkeypatch):
    """Centroid on floor but moving — down_since should reset."""
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    kf = make_kf(speed=SPEED_STILL_THRESHOLD + 10, cy=FLOOR_Y + 10)  # on floor but moving
    monkeypatch.setattr(time, "time", lambda: now)
    sm.update(kf, make_detection())
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS + 1)
    sm.update(kf, make_detection())
    assert sm.state != "FALL_SUSPECTED"


def test_down_since_cleared_on_leaving_floor(monkeypatch):
    """Person gets up — _down_since must be cleared."""
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    sm.update(make_kf_down(), make_detection())
    assert sm._down_since is not None
    monkeypatch.setattr(time, "time", lambda: now + 0.1)
    sm.update(make_kf_upright(), make_detection())
    assert sm._down_since is None


def test_emits_on_state_transition(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    sm.update(make_kf_upright(speed=100.0), make_detection())
    monkeypatch.setattr(time, "time", lambda: now + DEBOUNCE_SECONDS + 0.1)
    sm.update(make_kf_upright(speed=100.0), make_detection())
    assert sm.state == "PRESENT_NORMAL"
    t_absent = now + DEBOUNCE_SECONDS + 0.1 + ABSENCE_THRESHOLD + 0.2
    monkeypatch.setattr(time, "time", lambda: t_absent)
    sm.update(make_kf(), None)
    monkeypatch.setattr(time, "time", lambda: t_absent + DEBOUNCE_SECONDS + 0.1)
    sm.update(make_kf(), None)
    assert sm.state == "ABSENT"
    assert any(e.state == "ABSENT" for e in events)
