import time
import pytest
from unittest.mock import MagicMock
from device.kalman import KalmanFilter
from device.state_machine import (
    StateMachine,
    VY_FALL_THRESHOLD,
    ASPECT_FALL_THRESHOLD,
    FALL_CONFIRM_SECONDS,
    SPEED_STILL_THRESHOLD,
    STILL_SECONDS,
    DEBOUNCE_SECONDS,
    ABSENCE_THRESHOLD,
)
from device.perception import Detection


def make_detection(cx=100, cy=100, area=5000, aspect_ratio=0.4):
    return Detection(cx=cx, cy=cy, area=area, aspect_ratio=aspect_ratio, timestamp=time.time())


def make_kf(speed=50.0, vy=0.0, covariance_trace=20.0):
    kf = MagicMock(spec=KalmanFilter)
    kf.speed = speed
    kf.vy = vy
    kf.covariance_trace = covariance_trace
    kf.is_confident = covariance_trace < 200.0
    kf.is_uncertain = covariance_trace >= 200.0
    return kf


def tick(sm, kf, detection, t):
    """Single update at a fixed time."""
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(time, "time", lambda: t)
        sm.update(kf, detection)


def test_present_normal_when_moving(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    sm.update(make_kf(speed=100.0), make_detection())
    # After debounce
    monkeypatch.setattr(time, "time", lambda: now + DEBOUNCE_SECONDS + 0.1)
    sm.update(make_kf(speed=100.0), make_detection())
    assert sm.state == "PRESENT_NORMAL"


def test_absent_after_absence_threshold(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    # First call: raw state = ABSENT, candidate starts
    monkeypatch.setattr(time, "time", lambda: now + ABSENCE_THRESHOLD + 0.1)
    sm.update(make_kf(), None)
    # Second call: past debounce, transition commits
    monkeypatch.setattr(time, "time", lambda: now + ABSENCE_THRESHOLD + DEBOUNCE_SECONDS + 0.2)
    sm.update(make_kf(), None)
    assert sm.state == "ABSENT"


def test_uncertain_before_absence_threshold(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    # Just under absence threshold
    monkeypatch.setattr(time, "time", lambda: now + ABSENCE_THRESHOLD - 0.5)
    sm.update(make_kf(), None)
    assert sm.state == "UNCERTAIN"


def test_fall_not_confirmed_on_vy_spike_alone(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    # vy spike but normal aspect ratio
    kf = make_kf(speed=10.0, vy=VY_FALL_THRESHOLD + 1)
    sm.update(kf, make_detection(aspect_ratio=0.4))
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS + 1)
    sm.update(kf, make_detection(aspect_ratio=0.4))
    assert sm.state != "FALL_SUSPECTED"


def test_fall_not_confirmed_on_aspect_ratio_alone(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    kf = make_kf(speed=10.0, vy=0.0)
    sm.update(kf, make_detection(aspect_ratio=ASPECT_FALL_THRESHOLD + 0.5))
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS + 1)
    sm.update(kf, make_detection(aspect_ratio=ASPECT_FALL_THRESHOLD + 0.5))
    assert sm.state != "FALL_SUSPECTED"


def test_fall_not_confirmed_before_window(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    kf = make_kf(speed=10.0, vy=VY_FALL_THRESHOLD + 1)
    det = make_detection(aspect_ratio=ASPECT_FALL_THRESHOLD + 0.5)
    sm.update(kf, det)
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS - 0.5)
    sm.update(kf, det)
    assert sm.state != "FALL_SUSPECTED"


def test_fall_confirmed_after_window(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    kf_fall = make_kf(speed=SPEED_STILL_THRESHOLD - 1, vy=VY_FALL_THRESHOLD + 1)
    det = make_detection(aspect_ratio=ASPECT_FALL_THRESHOLD + 0.5)
    sm.update(kf_fall, det)
    # Past confirmation window — raw state becomes FALL_SUSPECTED, candidate starts
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS + 0.1)
    sm.update(kf_fall, det)
    # Past debounce — transition commits
    monkeypatch.setattr(time, "time", lambda: now + FALL_CONFIRM_SECONDS + DEBOUNCE_SECONDS + 0.2)
    sm.update(kf_fall, det)
    assert sm.state == "FALL_SUSPECTED"


def test_fall_candidate_cleared_on_no_detection(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    kf = make_kf(speed=10.0, vy=VY_FALL_THRESHOLD + 1)
    sm.update(kf, make_detection(aspect_ratio=ASPECT_FALL_THRESHOLD + 0.5))
    assert sm._fall_candidate_at is not None
    sm.update(make_kf(), None)
    assert sm._fall_candidate_at is None


def test_emits_on_state_transition(monkeypatch):
    events = []
    sm = StateMachine(emit_fn=events.append, source="fixture")
    now = time.time()
    # Establish PRESENT_NORMAL
    monkeypatch.setattr(time, "time", lambda: now)
    sm.update(make_kf(speed=100.0), make_detection())
    monkeypatch.setattr(time, "time", lambda: now + DEBOUNCE_SECONDS + 0.1)
    sm.update(make_kf(speed=100.0), make_detection())
    assert sm.state == "PRESENT_NORMAL"
    # Jump well past absence threshold from last detection time
    t_absent = now + DEBOUNCE_SECONDS + 0.1 + ABSENCE_THRESHOLD + 0.2
    monkeypatch.setattr(time, "time", lambda: t_absent)
    sm.update(make_kf(), None)
    # Debounce passes, ABSENT commits + emits
    monkeypatch.setattr(time, "time", lambda: t_absent + DEBOUNCE_SECONDS + 0.1)
    sm.update(make_kf(), None)
    assert sm.state == "ABSENT"
    assert any(e.state == "ABSENT" for e in events)
