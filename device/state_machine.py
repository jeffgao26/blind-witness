import time
from contracts.events import StateEvent, Source, LOW_COV, HIGH_COV, STREAM

# Tunable thresholds (velocities are px/SECOND — the Kalman state is in px/s).
SPEED_STILL_THRESHOLD = 25.0   # below this speed, the person is "not really moving"
STILL_SECONDS         = 3.0    # held still + present this long → PRESENT_STILL
ABSENCE_THRESHOLD     = 4.0    # no detection this long → ABSENT (else UNCERTAIN buffer)
DEBOUNCE_SECONDS      = 0.4    # a new state must persist this long before we commit/emit

# Fall detection — POSITION + STILLNESS, not velocity/aspect.
# Validated on 3 locked-camera collections (runs 4-6, 3 rooms): a fallen person's
# tracked centroid ends in the lower part of the frame (cy/H >= ~0.66) and stays
# still, while walking (<=0.52) and sitting in a chair (<=0.59) end higher. Velocity
# and bbox aspect did NOT separate (see tools/RESULTS.md). We use the Kalman position,
# which holds the last estimate through MOG2 dropout when a still body is absorbed
# into the background — so "fell and lay motionless" stays detectable.
# FLOOR_FRAC is camera-dependent: calibrate the floor zone per install.
FRAME_H               = 240    # production capture height (px); cy is normalized by this
FLOOR_FRAC            = 0.63   # centroid below this fraction of the frame = "on the floor"
FALL_CONFIRM_SECONDS  = 2.0    # must stay down+still this long to confirm FALL_SUSPECTED

# Kept for the contract / future use (aspect ratio still travels on Detection).
ASPECT_FALL_THRESHOLD = 1.2

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

    def __init__(self, emit_fn, source: Source = "live",
                 frame_h: int = FRAME_H, floor_frac: float = FLOOR_FRAC):
        """
        emit_fn: callable that accepts a StateEvent — decouples transport (Redis, SQLite, stdout)
        frame_h / floor_frac: floor-zone calibration (centroid below floor_frac*frame_h
            of the frame, while still, reads as on-the-floor). Tune per camera install.
        """
        self.emit_fn = emit_fn
        self.source = source
        self.floor_y = floor_frac * frame_h

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
        self._down_since: float | None = None
        self._started_at = now

    # ------------------------------------------------------------------
    def update(self, kf, detection, now: float | None = None):
        """
        Call every frame.
        kf: KalmanFilter instance (post predict+update)
        detection: Detection | None
        now: override the clock (for deterministic offline replay/testing)
        """
        if now is None:
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
        if detection is not None:
            self._last_detection_at = now

        still = kf.speed < SPEED_STILL_THRESHOLD

        # --- Fall = centroid in the floor zone AND still, sustained. ---
        # Uses the Kalman position (not the raw detection), so a person who fell and
        # lay motionless still reads as "down" even after MOG2 absorbs them and the
        # detection drops out. This is what makes FALL_SUSPECTED robust.
        on_floor = kf.position[1] >= self.floor_y
        if on_floor and still:
            if self._down_since is None:
                self._down_since = now
            if (now - self._down_since) >= FALL_CONFIRM_SECONDS:
                return "FALL_SUSPECTED"
            return "UNCERTAIN"      # down but not yet confirmed
        else:
            self._down_since = None

        if detection is None:
            self._still_since = None
            absent_for = (now - self._last_detection_at
                          if self._last_detection_at is not None
                          else now - self._started_at)
            # Prolonged absence is a committed ABSENT; the gap before is the UNCERTAIN
            # buffer, during which the covariance is visibly climbing.
            return "ABSENT" if absent_for >= ABSENCE_THRESHOLD else "UNCERTAIN"

        # Present, upright (not on floor). Sustained low motion → PRESENT_STILL.
        if still:
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
