# Constant — 5-Hour Build Plan (2 people, Pi + webcam in hand)

## Core design principles

1. **Minimize compute** — emit only on confirmed state changes + heartbeat. Redis
   stays lightweight, Claude API calls are rare.
2. **False positive minimization** — a false alarm (flagging an emergency when
   the elder is fine) is worse than being slow. Every escalation path has a
   confirmation window before it fires.
3. **Flag absence, not unusual presence** — if someone is in frame and moving,
   that is always `PRESENT_NORMAL`. Pushups, cooking, exercise are all the same.
   The only in-frame concern is sustained stillness. The dangerous pattern is:
   in-frame → out-of-frame → stays out past baseline expectation.
4. **`UNCERTAIN` is a buffer, not an alarm** — it absorbs ambiguous transitions
   and prevents premature escalation. Claude treats it as "watch and wait."
5. **Structural privacy** — the monitoring loop has no code path to video.
   Provable by `grep -ri emergency device/` → no results.

---

## Scope decisions

| Area | 5h version | Cut |
|---|---|---|
| CV perception | MOG2 background subtraction → largest-contour centroid + bbox | face/identity (never in scope) |
| Estimation | Hand-rolled 4-state Kalman `[x,y,vx,vy]`, covariance_trace as confidence | filterpy, tuning sweeps |
| State machine | 5 states, confirmation windows, covariance-gated transitions | activity classification |
| Emission | State transitions (confirmed) + heartbeat only | per-frame or per-detection |
| Baseline | Hardcoded per-hour expected-zone dict | real windowed ML |
| Reasoning | Claude call only on confirmed `ABSENT_UNEXPECTED` or prolonged `PRESENT_STILL` | `UNCERTAIN` alone is not enough |
| Emergency | TTS prompt → 10s wait → cv2 clip → drop to family-view folder | real encryption |
| UI | Flask: /status /debug /family | Kivy, polish |
| Observability | Sentry init both sides + kill-process demo | deep instrumentation |

---

## State machine

```
In frame + any movement          →  PRESENT_NORMAL      (pushups, cooking, walking — all same)
In frame + no movement > 3min    →  PRESENT_STILL       (asleep? unconscious? watching TV)
Out of frame + expected hour     →  ABSENT_EXPECTED
Out of frame + unexpected hour   →  UNCERTAIN  (buffer — wait for confirmation)
UNCERTAIN + duration > threshold →  ABSENT_UNEXPECTED   (confirmed, escalate)
Centroid just lost / cov spiking →  UNCERTAIN
```

**Confirmation windows (tunable constants in `state_machine.py`):**

| Transition | Window before confirming |
|---|---|
| → `ABSENT_UNEXPECTED` | 5–10 minutes |
| → `PRESENT_STILL` | 3 minutes |
| → `UNCERTAIN` | immediate (watchlist, not alarm) |
| → `PRESENT_NORMAL` | ~5 seconds (fast to confirm safe) |

**Emission rate:**
- Stable (`PRESENT_NORMAL`, `ABSENT_EXPECTED`): heartbeat every 30s
- `UNCERTAIN` or any active transition: immediate emit + every 5s until resolved
- Confirmed `ABSENT_UNEXPECTED` or `PRESENT_STILL`: immediate emit → triggers Claude

---

## Event contract (freeze at 0:15, never change)

```python
# contracts/events.py
STREAM = "eldercare:events"

{
    "timestamp":          float,   # unix epoch
    "state":              str,     # one of 5 labels above
    "covariance_trace":   float,   # tr(P) — confidence scalar; <50 stable, >200 uncertain
    "duration_in_state":  float,   # seconds held in current state
    "zone":               str,     # "in_frame" | "out_of_frame"
}
```

Emergency trigger back to Pi: B writes `severity:critical` to a separate Redis
key `eldercare:trigger`. Pi polls it in a lightweight side loop.

---

## Repo layout (also the privacy proof)

```
constant/
  contracts/events.py        # SHARED: schema + stream name. Frozen at 0:15.
  device/                    # PERSON A — Pi
    perception.py            # webcam + MOG2 + centroid (frame released immediately)
    kalman.py                # hand-rolled 4-state filter + covariance_trace
    state_machine.py         # 5 states + confirmation windows + emit to Redis
    monitoring_loop.py       # capture→cv→kalman→state→emit. NO emergency import.
  emergency/                 # PERSON A — isolated
    consent_video.py         # TTS → wait → cv2 burst → write clip
  pipeline/                  # PERSON B — laptop/cloud
    consumer.py              # Redis Streams → SQLite
    baseline.py              # per-hour expected-zone dict + anomaly flag
    reasoning.py             # Claude call → severity + family note
    store.py                 # SQLite schema + queries
    app.py                   # Flask: /status /debug /family
  tools/fixtures.py          # SHARED: scripted event timeline → Redis (B's unblocker)
  obs.py                     # SHARED: Sentry init
```

---

## Timeline

### 0:00–0:15 — Contract (both, together)
- Agree on schema above. Write `contracts/events.py`. Done. Never revisit.
- Agree on covariance thresholds: `LOW_COV = 50`, `HIGH_COV = 200` (tune later).
- Redis up (`redis-server` or `docker run -p6379:6379 redis`).
- Verify: Claude API key, Sentry DSN, `redis-cli ping`.

### 0:15–0:30 — B writes fixtures, A sets up Pi
- B writes `tools/fixtures.py`: ~25 lines, scripted day (normal → uncertain →
  confirmed unexpected absence). B is now fully unblocked.
- A: webcam working, OpenCV imports, `cv2.VideoCapture(0)` opens.

### 0:30–3:30 — Parallel build (3h, no coordination needed)

**Person A — Device:**
1. `perception.py` — MOG2 + centroid, frame released immediately (~45m)
2. `kalman.py` — predict every frame, update on detection, covariance_trace (~60m)
3. `state_machine.py` — 5 states + confirmation windows + uncertainty-driven
   emission rate + Redis publish (~60m)
4. `emergency/consent_video.py` — TTS → wait → clip → drop to folder (~30m)
5. Buffer: tune confirmation thresholds against live webcam

**Person B — Pipeline + UI + Claude:**
1. `consumer.py` + `store.py` — Redis → SQLite, works against fixtures (~45m)
2. `baseline.py` — per-hour dict + anomaly flag (~30m)
3. `reasoning.py` — Claude call on `ABSENT_UNEXPECTED`/`PRESENT_STILL` only (~45m)
4. `app.py` — Flask /status /debug /family (~60m)

### 3:30–4:30 — Integration
- Point `monitoring_loop.py` at B's Redis. If contract held, 5-minute hookup.
- Walk full chain on real movement: normal → leave frame → covariance rises →
  UNCERTAIN → confirmation window expires → ABSENT_UNEXPECTED → Claude note.
- Wire emergency trigger: B writes to `eldercare:trigger`, Pi picks it up,
  TTS fires, test both branches (respond = cancel, silence = clip).

### 4:30–5:00 — Reliability + rehearsal
- Sentry on both processes; kill `monitoring_loop.py` → heartbeat stops →
  pipeline flags gap.
- Run demo script twice. Fixture replayer as fallback if live CV misbehaves.

---

## Verification checklist

- [ ] `grep -ri emergency device/` → no results
- [ ] Pushups/movement in frame → stays `PRESENT_NORMAL`, no false alert
- [ ] Leave frame → `UNCERTAIN` immediately, `ABSENT_UNEXPECTED` only after window
- [ ] `redis-cli XLEN eldercare:events` grows on transitions + heartbeat only
- [ ] Claude only called on `ABSENT_UNEXPECTED` / confirmed `PRESENT_STILL`
- [ ] Emergency: TTS fires → respond cancels, silence produces clip
- [ ] Kill `monitoring_loop.py` → Sentry captures it, pipeline detects gap

---

## Honest gaps to name in the pitch

- Baseline is seeded, not learned (real deploy needs days of data).
- Emergency "encrypted one-time channel" is a file drop for the demo.
- Centroid tracking is coarse — "deviation from pattern," not fall detection.
- `PRESENT_STILL` can't distinguish sleep from unconsciousness — that's by design,
  and the honest answer is the confirmation window + consent gate before any alarm.
