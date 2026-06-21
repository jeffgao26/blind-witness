from dataclasses import dataclass, asdict
from typing import Literal

STREAM = "eldercare:events"

State = Literal[
    "PRESENT_NORMAL",   # in frame, moving
    "PRESENT_STILL",    # in frame, motionless > threshold
    "FALL_SUSPECTED",   # vy spike + aspect ratio flip + stillness
    "ABSENT",           # out of frame
    "UNCERTAIN",        # transitioning / low confidence buffer
]

Source = Literal["live", "fixture"]


@dataclass
class StateEvent:
    timestamp: float          # unix epoch
    state: str                # one of State literals
    covariance_trace: float   # tr(P) from Kalman — confidence scalar
    duration_in_state: float  # seconds held in current state
    zone: str                 # "in_frame" | "out_of_frame"
    source: str               # "live" | "fixture"

    def to_redis(self) -> dict:
        return {k: str(v) for k, v in asdict(self).items()}

    @classmethod
    def from_redis(cls, d: dict) -> "StateEvent":
        return cls(
            timestamp=float(d["timestamp"]),
            state=d["state"],
            covariance_trace=float(d["covariance_trace"]),
            duration_in_state=float(d["duration_in_state"]),
            zone=d["zone"],
            source=d["source"],
        )


# Covariance thresholds — must match kalman.py
LOW_COV  = 50.0
HIGH_COV = 200.0
