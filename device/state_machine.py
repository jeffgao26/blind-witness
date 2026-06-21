import time
from contracts.events import StateEvent, Source, LOW_COV, HIGH_COV, STREAM

# Tunable thresholds (velocities are px/SECOND — the Kalman state is in px/s).
SPEED_STILL_THRESHOLD = 25.0   # below this speed, the person is "not really moving"
STILL_SECONDS         = 3.0    # held still + present this long → PRESENT_STILL
ABSENCE_THRESHOLD     = 4.0    # no detection this long → ABSENT (else UNCERTAIN buffer)
DEBOUNCE_SECONDS      = 0.4    # a new state must persist this long before we commit/emit

# Fall detection
VY_FALL_THRESHOLD     = 150.0  # px/s downward velocity spike → fall candidate
ASPECT_FALL_THRESHOLD = 1.2    # bbox width/height — above this = wide/flat = fallen
FALL_CONFIRM_SECONDS  = 3.0    # must stay still after the spike to confirm FALL_SUSPECTED

# Sampling rates (seconds between heartbeat emits) — the cadence is uncertainty-driven.
HEARTBEAT_STABLE    = 30.0
HEARTBEAT_UNCERTAIN = 2.0


class StateMachine:
    """
    Derives state from Kalman filter output and Detection.
    Emits StateEvent on confirmed (debounced) transitions and on a heartbeat whose
    rate is driven by uncertainty: slow when confident, fast when the covariance is
    high or the state is volatile.

    Scalability note: new use cases (night wandering, med reminders) should
    add new states and thresholds here without modifying fall detection logic.
    """

    def __init__(self, emit_fn, source: Source = "live"):
        """
        emit_fn: callable that accepts a StateEvent — decouples transport (Redis, SQLite, stdout)
        """
        self.emit_fn = emit_fn
        self.source = source

        now = time.time()
        self.state = "UNCERTAIN"
        self.state_entered_at = now
        self.last_emit_at = 0.0
        self.current_interval = HEARTBEAT_UNCERTAIN  # surfaced on the debug view

        # Debounce: a proposed state must persist DEBOUNCE_SECONDS before we commit it.
        self._cand_state = "UNCERTAIN"
        self._cand_since = now

        # Presence / absence / fall tracking
        self._last_detection_at: float | None = None
        self._still_since: float | None = None
        self._fall_candidate_at: float | None = None
        self._started_at = now

    # ------------------------------------------------------------------
    def update(self, kf, detection):
        """
        Call every frame.
        kf: KalmanFilter instance (post predict+update)
        detection: Detection | None
        """
        now = time.time()
        raw = self._derive_state(kf, detection, now)

        # --- debounce: only commit a transition once the new state has held ---
        if raw != self._cand_state:
            self._cand_state = raw
            self._cand_since = now
        committed_change = False
        if raw != self.state and (now - self._cand_since) >= DEBOUNCE_SECONDS:
            self.state = raw
            self.state_entered_at = now
            committed_change = True

        # --- uncertainty-driven cadence ---
        # Slow heartbeat when the situation is settled; fast when we're actively
        # unsure. UNCERTAIN and a fall candidate are always volatile. A present
        # person we're losing (covariance climbing past HIGH_COV) goes fast too.
        # A committed ABSENT is settled — high covariance there is expected, not news.
        if self.state in ("PRESENT_NORMAL", "PRESENT_STILL"):
            confident = kf.covariance_trace < HIGH_COV
        elif self.state == "ABSENT":
            confident = True
        else:  # UNCERTAIN, FALL_SUSPECTED
            confident = False
        self.current_interval = HEARTBEAT_STABLE if confident else HEARTBEAT_UNCERTAIN

        if committed_change or (now - self.last_emit_at) >= self.current_interval:
            self._emit(kf, now)

    # ------------------------------------------------------------------
    def _derive_state(self, kf, detection, now: float) -> str:
        if detection is None:
            self._still_since = None
            self._fall_candidate_at = None
            absent_for = (now - self._last_detection_at
                          if self._last_detection_at is not None
                          else now - self._started_at)
            # Prolonged absence is a committed ABSENT; the gap before that is the
            # UNCERTAIN buffer, during which the covariance is visibly climbing.
            return "ABSENT" if absent_for >= ABSENCE_THRESHOLD else "UNCERTAIN"

        # Detection present.
        self._last_detection_at = now

        # Fall detection — downward velocity spike + wide/flat bbox, then held still.
        if kf.vy > VY_FALL_THRESHOLD and detection.aspect_ratio > ASPECT_FALL_THRESHOLD:
            if self._fall_candidate_at is None:
                self._fall_candidate_at = now
        if self._fall_candidate_at is not None:
            still = kf.speed < SPEED_STILL_THRESHOLD
            held = (now - self._fall_candidate_at) >= FALL_CONFIRM_SECONDS
            if still and held:
                return "FALL_SUSPECTED"
            return "UNCERTAIN"

        # Present + low motion sustained → PRESENT_STILL; otherwise normal presence.
        if kf.speed < SPEED_STILL_THRESHOLD:
            if self._still_since is None:
                self._still_since = now
            if (now - self._still_since) >= STILL_SECONDS:
                return "PRESENT_STILL"
            return "PRESENT_NORMAL"
        self._still_since = None
        return "PRESENT_NORMAL"

    # ------------------------------------------------------------------
    def _emit(self, kf, now: float) -> None:
        event = StateEvent(
            timestamp=now,
            state=self.state,
            covariance_trace=kf.covariance_trace,
            duration_in_state=now - self.state_entered_at,
            zone="in_frame" if self.state not in ("ABSENT", "UNCERTAIN") else "out_of_frame",
            source=self.source,
        )
        self.emit_fn(event)
        self.last_emit_at = now

    @property
    def current_sample_hz(self) -> float:
        """Effective heartbeat rate — surfaced on the debug view."""
        return 1.0 / self.current_interval if self.current_interval > 0 else 0.0
