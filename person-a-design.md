# Person A — Device Design Document

## Role

You own everything that runs on the Pi: capture, perception, state estimation,
event emission, emergency video, and the touchscreen UI stub. You publish to
Redis. You never call the Claude API.

---

## The contract that unblocks parallel work

Person B builds entirely against `tools/fixtures.py` from minute 30. The only
thing that must be agreed on before you split is the **event schema**. Freeze
this first, touch nothing after.

```python
# contracts/events.py
from dataclasses import dataclass

STREAM = "eldercare:events"

@dataclass
class StateEvent:
    timestamp: float       # unix epoch float
    state: str             # one of the 5 state labels below
    covariance_trace: float  # scalar summary of Kalman covariance (tr(P))
    duration_in_state: float # seconds in current state
    zone: str              # "in_frame" | "out_of_frame" (expand later if needed)

# Valid state labels
STATES = {
    "PRESENT_NORMAL",
    "PRESENT_STILL",
    "ABSENT_EXPECTED",
    "ABSENT_UNEXPECTED",
    "UNCERTAIN",
}
```

Person B reads from this. You write to it. As long as the JSON keys match,
you never need to coordinate again until integration at hour 3:30.

---

## Module breakdown

### `device/perception.py`

Responsibilities:
- Open webcam via `cv2.VideoCapture(0)`
- Apply `cv2.createBackgroundSubtractorMOG2` each frame
- Find contours in the foreground mask, take the largest
- Extract centroid `(cx, cy)` and bounding box area
- **Release the frame buffer immediately after extraction** — this is the
  literal privacy enforcement point; nothing downstream ever sees a pixel

Output: yields `Detection(cx, cy, area, timestamp)` or `None` (no foreground)

```python
# perception.py sketch
def detections(cap):
    fgbg = cv2.createBackgroundSubtractorMOG2()
    while True:
        ret, frame = cap.read()
        if not ret:
            yield None; continue
        mask = fgbg.apply(frame)
        frame = None  # release immediately
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            yield None; continue
        c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(c) < MIN_AREA:
            yield None; continue
        M = cv2.moments(c)
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        yield Detection(cx, cy, cv2.contourArea(c), time.time())
```

---

### `device/kalman.py`

State vector: `[x, y, vx, vy]` — constant-velocity model.

Matrices (hand-rolled, no filterpy):

```
F (transition):     H (observation):
1 0 dt 0            1 0 0 0
0 1 0  dt           0 1 0 0
0 0 1  0
0 0 0  1

Q (process noise): small diagonal, tune empirically
R (measurement noise): larger diagonal, reflects centroid jitter
P (initial covariance): large diagonal (high uncertainty at start)
```

Public interface:
- `predict(dt)` → updates `x`, `P`; call every frame
- `update(cx, cy)` → Kalman update step; call only when detection exists
- `covariance_trace` → `float`, property, `np.trace(self.P)` — the core
  uncertainty signal used by the state machine and event emitter

Predict-only on missed detections (occlusion / out of frame) — the filter
holds its last estimate and uncertainty grows, which is intentional signal.

---

### `device/state_machine.py`

Derives a state label from Kalman output. Transitions on thresholds:

| Condition | State |
|---|---|
| Detection present, covariance_trace < LOW_COV, velocity low | `PRESENT_NORMAL` |
| Detection present, covariance_trace < LOW_COV, velocity near zero for > STILL_SECS | `PRESENT_STILL` |
| No detection, within expected-absence hours (from baseline dict) | `ABSENT_EXPECTED` |
| No detection, outside expected-absence hours, duration > ABSENCE_THRESHOLD | `ABSENT_UNEXPECTED` |
| Covariance_trace > HIGH_COV or transitioning between above | `UNCERTAIN` |

Threshold constants live at the top of the file — tunable during demo.

**Sampling rate** is covariance-driven:
- Stable state (`PRESENT_NORMAL`, `ABSENT_EXPECTED`): emit heartbeat every 30s
- `UNCERTAIN` or any transition: emit immediately, then every 5s until resolved

Emits via `redis_client.xadd(STREAM, asdict(event))`.

---

### `device/monitoring_loop.py`

The main loop. Wires together perception → kalman → state_machine → emit.

**Critical constraint: this file must import nothing from `emergency/`.**
That separation is the privacy proof. `grep -ri emergency device/` must return
nothing.

```python
# monitoring_loop.py — imports only from device/ and contracts/
from device.perception import detections
from device.kalman import KalmanFilter
from device.state_machine import StateMachine
import redis, cv2, time
```

---

### `emergency/consent_video.py`

Completely separate module. Called only from an external trigger (severity
threshold hit by the pipeline, delivered back to the Pi via a separate Redis
key or a simple HTTP call from B's Flask app).

Flow:
1. `pyttsx3` speaks: *"Are you okay? I'm about to let [name] see this room — say no to cancel."*
2. Wait 10 seconds for keypress (or mic input if time allows)
3. If no response: `cv2.VideoCapture(0)` for 10–15s, write clip to `clips/`
4. "Send" = copy to `pipeline/static/family_clip.mp4` (the stub for a real
   encrypted channel)
5. Delete from `clips/` immediately after

This module has no import from `device/`. It opens its own capture handle.

---

## Fixtures contract (your obligation to B)

`tools/fixtures.py` is B's unblocker. You don't write it — B does — but you
need to make sure your real emitter produces identical JSON keys so integration
is a 5-minute hookup.

Verify before you split:
```bash
# B runs fixtures, you inspect what lands in Redis
redis-cli XRANGE eldercare:events - + COUNT 3
# Keys should match contracts/events.py exactly
```

---

## Dev setup (no Pi needed early)

You can develop and test `perception.py`, `kalman.py`, and `state_machine.py`
entirely on your laptop with a webcam or a pre-recorded video file:

```python
cap = cv2.VideoCapture("test_clip.mp4")  # swap for 0 (webcam) or Pi later
```

Only `monitoring_loop.py` needs to run on the Pi for real. Everything else is
portable.

---

## Integration point (hour 3:30)

The only wiring needed at integration:
1. Pi runs `monitoring_loop.py`, emitting to Redis on the same host/port B's
   consumer is pointed at.
2. Confirm `redis-cli XLEN eldercare:events` grows when you move in frame.
3. B's `/debug` view should immediately reflect your state — no other changes
   needed if the contract held.

---

## Verification checklist (your side)

- [ ] `grep -ri emergency device/` → no results
- [ ] Move in front of webcam → state transitions to `PRESENT_NORMAL`, low covariance
- [ ] Leave frame → covariance rises, state goes `UNCERTAIN` then `ABSENT_*`
- [ ] `redis-cli XLEN eldercare:events` grows on transitions and heartbeat
- [ ] Emergency path: manual trigger → hear TTS → respond cancels, silence produces clip
- [ ] Kill `monitoring_loop.py` → heartbeat stops; B's pipeline detects the gap
