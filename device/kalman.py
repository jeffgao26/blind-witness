import numpy as np


# Tunable noise constants
# PROCESS_NOISE is the acceleration spectral density of the constant-velocity model:
# how much real motion can deviate from "constant velocity" between frames. It is the
# knob that makes the covariance a *legible* uncertainty signal — large enough that a
# few predict-only frames (occlusion / out of frame) visibly grow tr(P), small enough
# that a tracked target settles well under LOW_COV.
PROCESS_NOISE = 600.0  # accel spectral density (px/s^2)^2 — tuned on-device
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

        self.R = np.eye(2) * MEASURE_NOISE
        self.P = np.eye(4) * INIT_COV

    # ------------------------------------------------------------------
    def _Q(self, dt: float) -> np.ndarray:
        """Discrete white-noise-acceleration process covariance for this dt.

        Unlike a static diagonal, this couples position and velocity and scales with
        dt, so predict-only steps inflate uncertainty the way they physically should:
        the longer we go without a detection, the less we know where the person is.
        """
        q = PROCESS_NOISE
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        return q * np.array([
            [dt4 / 4, 0.0,     dt3 / 2, 0.0    ],
            [0.0,     dt4 / 4, 0.0,     dt3 / 2],
            [dt3 / 2, 0.0,     dt2,     0.0    ],
            [0.0,     dt3 / 2, 0.0,     dt2    ],
        ])

    # ------------------------------------------------------------------
    def predict(self, dt: float) -> None:
        # Update F with current dt
        self.F[0, 2] = dt
        self.F[1, 3] = dt

        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self._Q(dt)

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
