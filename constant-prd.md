# Constant — Product Requirements Document

**Eldercare monitoring that's structurally incapable of surveillance**

Hackathon Project · Cal Hacks · June 2026

---

## 1. Summary

Constant is a passive home-monitoring device for families checking in on an aging parent or relative living alone. Unlike existing camera-based solutions, Constant is architecturally incapable of producing or storing surveillance video during normal operation — it only ever knows and transmits *state* (presence, movement pattern, uncertainty), never images. Video exists only behind a separate, consent-gated emergency path that the monitored person can refuse in real time.

**One-line pitch:** *Eldercare monitoring that can tell you something's wrong without ever being able to show anyone what's happening — because it only ever knows state, never sees a face.*

---

## 2. Problem

Families monitoring an aging relative living alone face a real, unresolved tradeoff:

- **Camera-based monitoring** (Ring-style, Nest-style) works, but many elders and families reject it — a live video feed of a private home, accessible to anyone with login credentials or vulnerable to a breach, feels invasive. Some elders specifically refuse cameras for this reason, leaving families with no passive option at all.
- **Wearables and check-in calls** are the privacy-respecting alternative, but they require active, ongoing cooperation — a button worn, a call answered. They fail silently the moment the elder forgets, refuses, or is unable to comply (which is often exactly the moment they're needed most).
- **No existing product is both passive (works without active cooperation) and structurally private (not "we promise not to look," but technically incapable of showing footage).**

This gap is the product opportunity.

---

## 3. Goals

| Goal | Success looks like |
|---|---|
| Passive monitoring | Works continuously with zero action required from the monitored person |
| Structural privacy | No code path exists for raw video to leave the device during normal operation — provable, not promised |
| Useful signal | Family is alerted to genuine deviations from normal pattern, not noise |
| Honest emergency handling | When something is seriously wrong, the system can still surface video — but only with the elder's real-time, revocable consent |
| Technical depth | Genuine Bayesian state estimation (Kalman filtering) and real streaming data engineering, not a thin demo wrapper |

### Non-goals
- Facial recognition or any identity-linked data
- Continuous or on-demand live video streaming as a default feature
- Diagnosing medical conditions — Constant flags deviations from pattern, it does not interpret medical causes

---

## 4. Users & Use Case

**Primary user (monitored):** an older adult living alone who wants independence, doesn't want to be watched, but is open to a device that notices if something's wrong.

**Secondary user (family/caregiver):** an adult child or relative who wants reassurance and a way to know quickly if something is off, without an always-on video feed they'd feel uncomfortable using — or that the elder would refuse.

**Core scenario:** A device sits in a high-traffic area of the home (kitchen, living room). Day to day, the family sees a simple status indicator: normal or needs attention. If the monitored person's movement pattern deviates significantly from their established baseline (e.g., no movement detected in the usual area well past their normal time), the system raises an alert and — only after asking the elder directly and getting no response — may release a short video clip to the family.

---

## 5. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  RASPBERRY PI (on-device, local)                             │
│                                                                │
│  ┌──────────────┐   ┌────────────────┐   ┌─────────────────┐ │
│  │  Webcam       │──▶│ CV Perception   │──▶│ Kalman Filter   │ │
│  │  capture      │   │ (background     │   │ state estimator │ │
│  │  (in-memory   │   │ subtraction,    │   │ (position,      │ │
│  │  only)        │   │ centroid only)  │   │ velocity,       │ │
│  │               │   │                 │   │ covariance)     │ │
│  └──────────────┘   └────────────────┘   └────────┬────────┘ │
│         │ frame discarded after extraction          │          │
│         ▼                                            ▼          │
│   (no code path to storage/transmission)     State Machine     │
│                                          (PRESENT_NORMAL,       │
│                                          PRESENT_STILL,         │
│                                          ABSENT_EXPECTED,       │
│                                          ABSENT_UNEXPECTED,     │
│                                          UNCERTAIN)             │
│                                                       │          │
│                                                       ▼          │
│                                          Event Emitter (state   │
│                                          + covariance summary   │
│                                          + timestamp only)      │
│                                                       │          │
│  ┌────────────────────────────────────────────────────┐        │
│  │  SEPARATE GATED PATH (only on severity threshold)    │        │
│  │  Local TTS prompt → wait for response → if none,     │        │
│  │  short video burst → encrypted one-time send →       │        │
│  │  deleted from device                                  │        │
│  └────────────────────────────────────────────────────┘        │
│                                                                │
│  Touchscreen UI: status indicator + debug/demo view           │
└───────────────────────────┬───────────────────────────────────┘
                             │ state events only (JSON, no media)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  PIPELINE (cloud/server side)                                 │
│                                                                │
│  Redis Streams (XADD eldercare:events)                        │
│         │                                                      │
│         ▼                                                      │
│  Consumer: windowed aggregation, baseline pattern modeling     │
│  (per time-of-day normal ranges)                                │
│         │                                                      │
│         ▼                                                      │
│  Time-series store (Postgres/SQLite) — state events only       │
│         │                                                      │
│         ▼                                                      │
│  Claude API — reasoning over structured state history,         │
│  drafts plain-language alert notes, decides escalation         │
│  severity, decides whether to trigger consent-gated check-in   │
│                                                                │
│  Sentry — instruments perception loop + ingestion pipeline     │
│  (latency, dropped frames, filter divergence, pipeline lag)    │
└─────────────────────────────────────────────────────────────┘
```

**Core architectural guarantee:** the always-on monitoring loop (capture → CV → Kalman filter → event emitter) has no function, import, or network call capable of transmitting or persisting a video frame. The emergency video path is a structurally separate module, only reachable through the consent-gate sequence. This separation is a deliberate code-organization decision, not just a runtime check — it should be visibly demonstrable in the codebase.

---

## 6. Why Pure CV, Not a Vision-LLM

This is a deliberate design choice, not a limitation:

1. **Privacy claim integrity** — sending frames to any external model (even briefly, even for inference) means video left the device. The entire privacy architecture requires perception to happen on-device with classical, fully local methods.
2. **Latency and cost** — continuous always-on monitoring at real frame rates is impractical to run through LLM calls per frame; classical CV (background subtraction, centroid tracking) runs natively on Pi CPU.
3. **Auditability** — for a safety-relevant product, a deterministic, explainable pipeline (why did this alert fire?) is more defensible than a vision-LLM's opaque reasoning.

**Where the LLM does belong:** strictly downstream of perception, operating only on already-abstracted state data (numbers, timestamps, state labels) — never on pixels. Claude's job is judgment and language, not seeing.

---

## 7. Detailed Component Specs

### 7.1 Capture & Perception (Pi, on-device)
- OpenCV reads webcam frames continuously, in memory only.
- `cv2.createBackgroundSubtractorMOG2` (or simple frame differencing) isolates the moving foreground.
- Extract centroid `(x, y)` and rough bounding box size per frame.
- No face detection, no identity, no recognition of any kind.
- Frame buffer explicitly released immediately after extraction — this is the literal enforcement point of the privacy guarantee.

### 7.2 State Estimation (Pi)
- 2D Kalman filter, state vector `[x, y, vx, vy]`.
- Predict step every frame; update step when a detection is available; predict-only when detection is missing (occlusion / out of frame).
- Covariance matrix is the core uncertainty signal driving sampling rate and alerting.
- Derived state machine: `PRESENT_NORMAL`, `PRESENT_STILL`, `ABSENT_EXPECTED`, `ABSENT_UNEXPECTED`, `UNCERTAIN`.

### 7.3 Event Emission (Pi)
- Emits only on state transitions, plus a low-rate heartbeat.
- Payload: `{timestamp, state, covariance_summary, duration_in_state, zone}`.
- Sampling/transmission rate is uncertainty-driven: stable → infrequent heartbeat; uncertain/changing → immediate event + temporary higher-frequency checks until resolved.

### 7.4 Streaming Ingestion (Partner — Data Engineering)
- Pi publishes to Redis Stream (`XADD eldercare:events * ...`).
- Consumer process performs windowed aggregation and builds a per-time-of-day baseline (e.g., normally in kitchen 7–8am; absence then is not anomalous, absence at 2pm might be).
- Aggregated data lands in a queryable time-series store (Postgres or SQLite for hackathon scope).
- This is where irregular, bursty, semantically-tagged event handling — the genuine data engineering challenge — lives.

### 7.5 Reasoning Layer (Claude)
- Triggered on transition into `UNCERTAIN` or `ABSENT_UNEXPECTED`.
- Input: event + recent state history (text/JSON only).
- Output: escalation severity decision + plain-language note for family (e.g., *"No movement detected in the usual area for 40 minutes, outside her normal pattern for this time of day."*)
- Also decides whether to trigger the audio consent-check sequence before any further escalation.

### 7.6 Emergency Video Path (gated, separate code path)
Triggered only when **all** of the following hold:
1. State crosses a defined severity threshold.
2. Local TTS audibly prompts the monitored person: *"Are you okay? I'm about to let [family contact] see this room — say no to cancel."*
3. No response within a fixed window (e.g., 10 seconds).

If triggered: a short (10–15s) video clip is captured, sent through an encrypted, one-time-access channel to the family contact, then deleted from the device immediately after send. This module is implemented as a separate, clearly isolated code path from the monitoring loop — the monitoring loop itself has no reference to it.

### 7.7 Observability (Sentry)
- Instruments the Pi-side perception loop: frame processing latency, dropped frames, Kalman filter divergence/reset events.
- Instruments the ingestion pipeline: event lag, Redis connection health, consumer errors.

### 7.8 UI (Touchscreen, Pi)
- **Default view:** simple status indicator — green (normal), amber (uncertain), red (alert). No video, no detailed movement log, by design.
- **Debug/demo view (toggle, for judges):** live covariance graph, current state machine state, current sampling rate — shows the underlying mechanism without compromising the product's real-world UI philosophy.

---

## 8. Tech Stack

| Layer | Tool | Notes |
|---|---|---|
| Capture / CV | OpenCV | Background subtraction, centroid extraction only |
| State estimation | Custom or `filterpy` Kalman filter | Hand-rolling preferred for learning depth |
| Local audio prompt | On-device TTS (espeak/pyttsx3); Deepgram optional for quality, used only for the consent-prompt audio, never for monitoring | Keep on-device by default for the same privacy reasoning |
| Event transport | Redis Streams | Core, not decorative — handles irregular/bursty event data |
| Aggregation / storage | Python consumer + Postgres or SQLite | Time-series-indexed, state-events only |
| Reasoning | Claude API | Text-only calls, structured JSON in/out |
| Observability | Sentry SDK | On both Pi process and ingestion consumer |
| UI | Touchscreen — Flask/Kivy or HTML+JS | Status-first, debug view secondary |
| Emergency video | Separate OpenCV capture burst + encrypted one-time transfer | Deleted post-send; isolated module |

---

## 9. Demo Plan

1. **Normal operation:** show the touchscreen in default (status-only) view; person moves naturally in frame; status stays green; debug view shows low sampling rate, low covariance.
2. **Uncertainty event:** person leaves frame / occludes themselves; debug view shows covariance rising, sampling rate increasing, state transitioning to `UNCERTAIN`.
3. **Alert without video:** simulate prolonged absence past baseline; status flips to red; Claude-generated plain-language note appears for the "family" view — no video shown.
4. **Emergency path:** trigger severity threshold; local TTS audibly asks the consent question; demonstrate both outcomes — responding "I'm fine" cancels the path, vs. no response triggers a brief video send, visibly different code path highlighted.
5. **Reliability:** kill the perception process mid-demo; show Sentry capturing it and the pipeline flagging the gap rather than failing silently.

---

## 10. Team Split

**Embedded / CV / Estimation (you):**
- Capture pipeline, background subtraction, centroid extraction
- Kalman filter implementation and tuning
- State machine and uncertainty-driven event emission
- Emergency video path (isolated module)
- Touchscreen UI

**Data Engineering (partner):**
- Redis Streams ingestion and consumer design
- Windowed aggregation / per-time-of-day baseline modeling
- Time-series schema design and query layer
- Sentry pipeline-side instrumentation

**Shared:**
- Claude integration (reasoning layer, alert drafting)
- Demo script and staged failure/event scenarios

---

## 11. Risks & Honest Limitations

- **Centroid-based tracking is coarse** — it can't distinguish a fall from sitting down quickly; framed honestly as "deviation from established pattern," not medical diagnosis.
- **Baseline-building takes time** — a real deployment needs days/weeks of data to establish a meaningful "normal pattern"; for the hackathon demo, baseline will be seeded/simulated.
- **Lighting and occlusion affect CV reliability** — acknowledged directly in the pitch as a known constraint and a real v2 direction (e.g., multiple cameras, infrared).
- **Emergency video path is the one place the "no surveillance" claim has an exception** — this should be stated proactively in the pitch, not discovered by a judge's question. The exception is consent-gated and revocable by design, which is the honest answer to "what about real emergencies."

---

## 12. Resume / Learning Outcomes

- **You:** real-time computer vision pipeline design, Bayesian state estimation (Kalman filtering) implemented from first principles, uncertainty-driven systems design, privacy-by-architecture engineering.
- **Partner:** streaming data ingestion for irregular/bursty sources, time-windowed aggregation, schema design for semantically-tagged event data, observability instrumentation for a live pipeline.
