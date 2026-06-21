import time
from contracts.events import StateEvent, Source, LOW_COV, HIGH_COV, STREAM

# Tunable thresholds
STILL_SECONDS         = 180.0  # 3 min motionless in frame → PRESENT_STILL
VY_FALL_THRESHOLD     = 8.0    # px/frame downward velocity spike → fall candidate
ASPECT_FALL_THRESHOLD = 1.2    # width/height ratio — above this = wide/flat = fallen
FALL_CONFIRM_SECONDS  = 30.0   # must stay still after spike to confirm FALL_SUSPECTED
SPEED_STILL_THRESHOLD = 1.5    # px/frame — below this = not moving

# Sampling rates (seconds between heartbeat emits)
HEARTBEAT_STABLE    = 30.0
HEARTBEAT_UNCERTAIN = 5.0


class StateMachine:
    """
    Derives state from Kalman filter output and Detection.
    Emits StateEvent on confirmed transitions and heartbeat.

    Scalability note: new use cases (night wandering, med reminders) should
    add new states and thresholds here without modifying fall detection logic.
    """

    def __init__(self, emit_fn, source: Source = "live"):
        """
        emit_fn: callable that accepts a StateEvent — decouples transport (Redis, SQLite, stdout)
        """
        self.emit_fn = emit_fn
        self.source = source

        self.state = "UNCERTAIN"
        self.state_entered_at = time.time()
        self.last_emit_at = 0.0

        # Fall detection tracking
        self._fall_candidate_at: float | None = None  # time of vy spike

    # ------------------------------------------------------------------
    def update(self, kf, detection):
        """
        Call every frame.
        kf: KalmanFilter instance (post predict+update)
        detection: Detection | None
        """
        now = time.time()
        new_state = self._derive_state(kf, detection, now)

        if new_state != self.state:
            self.state = new_state
            self.state_entered_at = now
            self._emit(now)
        else:
            interval = HEARTBEAT_UNCERTAIN if self.state == "UNCERTAIN" else HEARTBEAT_STABLE
            if now - self.last_emit_at >= interval:
                self._emit(now)

    # ------------------------------------------------------------------
    def _derive_state(self, kf, detection, now: float) -> str:
        duration = now - self.state_entered_at

        if detection is None:
            self._fall_candidate_at = None
            return "ABSENT" if kf.is_confident else "UNCERTAIN"

        # Fall detection — check for vy spike + aspect ratio
        if kf.vy > VY_FALL_THRESHOLD and detection.aspect_ratio > ASPECT_FALL_THRESHOLD:
            if self._fall_candidate_at is None:
                self._fall_candidate_at = now

        # Confirm fall if candidate has been held and person is still
        if self._fall_candidate_at is not None:
            still = kf.speed < SPEED_STILL_THRESHOLD
            held_long_enough = (now - self._fall_candidate_at) >= FALL_CONFIRM_SECONDS
            if still and held_long_enough:
                return "FALL_SUSPECTED"
            # Candidate active but not yet confirmed — stay uncertain
            return "UNCERTAIN"

        # Normal presence states
        if kf.speed < SPEED_STILL_THRESHOLD:
            if duration >= STILL_SECONDS:
                return "PRESENT_STILL"
            return "UNCERTAIN"

        return "PRESENT_NORMAL"

    # ------------------------------------------------------------------
    def _emit(self, now: float) -> None:
        event = StateEvent(
            timestamp=now,
            state=self.state,
            covariance_trace=0.0,  # caller should patch this from kf.covariance_trace
            duration_in_state=now - self.state_entered_at,
            zone="in_frame" if self.state not in ("ABSENT", "UNCERTAIN") else "out_of_frame",
            source=self.source,
        )
        self.emit_fn(event)
        self.last_emit_at = now
