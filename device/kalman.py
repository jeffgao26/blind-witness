import numpy as np


# Tunable noise constants
PROCESS_NOISE = 1e-2   # Q diagonal — how much we trust the motion model
MEASURE_NOISE = 5.0    # R diagonal — how much we trust the centroid detection
INIT_COV      = 500.0  # P diagonal — high initial uncertainty

LOW_COV  = 50.0   # below this: filter is confident
HIGH_COV = 200.0  # above this: filter is uncertain


class KalmanFilter:
    """
    2D constant-velocity Kalman filter.
    State vector: [x, y, vx, vy]

    Usage:
        kf = KalmanFilter(cx, cy)
        kf.predict(dt)
        kf.update(cx, cy)       # call only when a detection exists
        kf.predict(dt)          # call without update on missed frames
        kf.covariance_trace     # scalar confidence signal
        kf.vy                   # vertical velocity — fall signal
    """

    def __init__(self, cx: float, cy: float):
        self.x = np.array([cx, cy, 0.0, 0.0], dtype=float)

        # State transition: x' = Fx (constant velocity)
        self.F = np.eye(4)

        # Observation: we measure x, y only
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ], dtype=float)

        self.Q = np.eye(4) * PROCESS_NOISE
        self.R = np.eye(2) * MEASURE_NOISE
        self.P = np.eye(4) * INIT_COV

    # ------------------------------------------------------------------
    def predict(self, dt: float) -> None:
        # Update F with current dt
        self.F[0, 2] = dt
        self.F[1, 3] = dt

        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q

    # ------------------------------------------------------------------
    def update(self, cx: float, cy: float) -> None:
        z = np.array([cx, cy], dtype=float)
        y = z - self.H @ self.x                          # innovation
        S = self.H @ self.P @ self.H.T + self.R          # innovation covariance
        K = self.P @ self.H.T @ np.linalg.inv(S)         # Kalman gain
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P

    # ------------------------------------------------------------------
    @property
    def position(self) -> tuple[float, float]:
        return self.x[0], self.x[1]

    @property
    def velocity(self) -> tuple[float, float]:
        return self.x[2], self.x[3]

    @property
    def vy(self) -> float:
        return self.x[3]

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.x[2:4]))

    @property
    def covariance_trace(self) -> float:
        return float(np.trace(self.P))

    @property
    def is_confident(self) -> bool:
        return self.covariance_trace < LOW_COV

    @property
    def is_uncertain(self) -> bool:
        return self.covariance_trace > HIGH_COV
