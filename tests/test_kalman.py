import pytest
from device.kalman import KalmanFilter, LOW_COV, HIGH_COV, INIT_COV


def test_initial_covariance_is_high():
    kf = KalmanFilter(100, 100)
    assert kf.covariance_trace > HIGH_COV


def test_covariance_shrinks_with_updates():
    kf = KalmanFilter(100, 100)
    initial = kf.covariance_trace
    for _ in range(30):
        kf.predict(0.033)
        kf.update(100, 100)
    assert kf.covariance_trace < initial


def test_covariance_grows_without_updates():
    kf = KalmanFilter(100, 100)
    # Converge first
    for _ in range(30):
        kf.predict(0.033)
        kf.update(100, 100)
    converged = kf.covariance_trace
    # Then predict-only
    for _ in range(30):
        kf.predict(0.033)
    assert kf.covariance_trace > converged


def test_position_tracks_stationary_detection():
    kf = KalmanFilter(100, 100)
    for _ in range(50):
        kf.predict(0.033)
        kf.update(100, 100)
    x, y = kf.position
    assert abs(x - 100) < 5
    assert abs(y - 100) < 5


def test_vy_positive_on_downward_movement():
    kf = KalmanFilter(100, 100)
    for i in range(20):
        kf.predict(0.033)
        kf.update(100, 100 + i * 5)  # moving downward (y increases)
    assert kf.vy > 0


def test_vy_near_zero_when_stationary():
    kf = KalmanFilter(100, 100)
    for _ in range(50):
        kf.predict(0.033)
        kf.update(100, 100)
    assert abs(kf.vy) < 1.0


def test_is_confident_after_convergence():
    kf = KalmanFilter(100, 100)
    for _ in range(50):
        kf.predict(0.033)
        kf.update(100, 100)
    assert kf.is_confident


def test_is_uncertain_after_predict_only():
    kf = KalmanFilter(100, 100)
    for _ in range(50):
        kf.predict(0.033)
        kf.update(100, 100)
    for _ in range(100):
        kf.predict(0.033)
    assert kf.is_uncertain
