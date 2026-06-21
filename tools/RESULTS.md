# Fall-detection tuning — results log

## Round 1 (320×240 @10fps) — 2 collections, 14 clips

Recorded with `tools/record_clip.py` (guided), analyzed with `tools/analyze_clip.py`.
Thresholds at test: `VY_FALL_THRESHOLD=150 px/s`, `ASPECT_FALL_THRESHOLD=1.2`,
`FALL_CONFIRM_SECONDS=3`, `SPEED_STILL_THRESHOLD=25 px/s`.

| clip | peak vy (px/s) | aspect @ peak vy | max aspect | fired |
|---|---|---|---|---|
| fall_side1 / 2     | 175 / 172 | 0.72 / 2.83 | 2.06 / 2.83 | no |
| fall_toward1 / 2   | 235 / 132 | 0.39 / 0.56 | 1.33 / 1.70 | no |
| fall_down1 / 2     | 218 / 144 | 1.34 / 0.81 | 2.19 / 2.89 | no |
| sit1 / 2 (neg)     | 121 / 194 | – | 1.93 / 2.42 | no |
| crouch1 / 2 (neg)  | 118 / 147 | – | 1.33 / 1.07 | no |
| couch1 / 2 (neg)   | 491 / 126 | – | 8.00 / 2.38 | no |
| walk1 / 2 (neg)    | 140 / 138 | – | 3.09 / 1.17 | no |

### Verdict: `vy` + aspect from a 320×240 centroid do NOT separate falls from non-falls.
1. **`vy` overlaps** — `couch` slow lie-down spiked to 491 (> every fall); `sit2`=194 beat
   4 of 6 falls. No vy threshold separates fall from sit/lie.
2. **Spike and flatten don't co-occur** — for 4 of 6 falls, aspect at the vy peak was <1
   (upright mid-drop; widen only after landing), so a "vy AND wide at the same frame"
   rule structurally can't fire — and didn't, on any clip.
3. **Aspect is noisy** — walk hit 3.09 and couch hit 8.0 (bbox fragments/shadows at low
   res), while lying on a couch is *legitimately* wide. Aspect alone is ambiguous.

Confirms PRD §11 ("can't distinguish a fall from sitting down quickly") empirically.

## Round 2 (640×480 @10fps) — run 3, 7 clips

Same tooling, area/dilate scaled to resolution via `tools/blob.py` (fair A/B test).

| clip | peak vy (px/s) | aspect @ peak vy | max aspect | fired |
|---|---|---|---|---|
| fall_side3   | 244 | 1.60 | 2.29 | no |
| fall_toward3 | 217 | 0.72 | 1.33 | no |
| fall_down3   | 230 | 0.47 | 1.33 | no |
| sit3 (neg)   | 192 | 1.01 | 1.33 | no |
| crouch3 (neg)| 274 | 0.87 | 1.55 | no |
| couch3 (neg) | 268 | 0.69 | 1.33 | no |
| walk3 (neg)  | 324 | 2.55 | 2.87 | no |

### Verdict: higher resolution did NOT separate falls from non-falls — arguably worse.
- `vy`: `walk3` (324) and `crouch3` (274) exceed every fall (217–244). Higher res amplified
  centroid jitter.
- aspect: `walk3` (2.87) tops everything; two of three falls sit at exactly 1.33.
- The recurring **1.33** = the frame's 4:3 ratio → MOG2 flagged the whole frame as foreground
  (lighting / auto-exposure shift), so the "person" box was the entire image. Global frame
  changes corrupt any feature at any resolution.

**Conclusion: the feature (centroid vy + bbox aspect from background subtraction) is the
limit, not resolution.** 21 clips across two resolutions, zero separation. Matches PRD §11.

## Round 3 (camera LOCKED, 320×240) — run 4

Added richer features (`tools/explore.py`: vertical position `cy`, drop, end-stillness)
and **locked the camera** (manual exposure/WB/focus via v4l2-ctl in `record_clip.py`) to
stop lighting/auto-exposure from flagging the whole frame as foreground.

**Detection cleaned up dramatically:** `fg_bad` (whole-frame-reject frames) went from
~50/29/20 in earlier runs to **1 on every clip**.

| clip | cy_end (0=top,1=floor) | end_still | verdict |
|---|---|---|---|
| fall_side4   | 0.79 | 0.10 | low+still |
| fall_toward4 | 0.83 | 0.06 | low+still |
| fall_down4   | 0.85 | 0.07 | low+still |
| walk4 (neg)  | 0.21 | 0.23 | high+moving — rejected |
| sit4 (neg)   | 0.54 | 0.02 | mid (chair) — rejected |
| crouch4 (neg)| 0.77 | 0.05 | low+still — FP |
| couch4 (neg) | 0.79 | 0.10 | low+still — FP |

**Finding:** with clean detection, the discriminator is **vertical position + stillness**,
NOT velocity or aspect. Rule "ends low (cy_end>0.75) AND still" catches all 3 falls and
correctly rejects walking and sitting (the common activities). Remaining confusers —
crouch and lie-on-couch — both genuinely end low+still, and are handled benignly by the
consent gate (the elder just says "I'm fine"). Fall detection and the stillness reframe
converge: "dropped low and went still unexpectedly → ask → escalate."

Caveat: n=1 per class. Need 2 more locked collections to set the cy_end/stillness
threshold and check the fall-vs-crouch/couch boundary.

## Round 4 (descent rate, 30fps) — run 7

Hypothesis: a fall drops FASTER than lying down. Measured sustained descent rate
(drop / 0.25s window, median-filtered) via `tools/descent.py`.

- 10fps baseline (run 4) *looked* promising: falls 1.6–2.2 vs slow lie-downs sit 0.75 /
  couch 0.94. But that came from 2-frame diffs — a single big centroid jump inflated it.
- **30fps (run 7) disproved it:** fall_side 0.77 ≈ sit 0.79; crouch 1.73 out-paced every
  fall; falls (0.77–1.37) fully overlap negatives. Measured properly, falls are NOT
  meaningfully faster than a brisk crouch/sit.

Pattern across all rounds: vy ✗, aspect ✗, resolution ✗, descent rate ✗ — every
single-feature signal from the **blob centroid** fails to replicate. Only **position
(ends low + still)** holds, and only to separate falls from walk/sit (not from lying down).

## Round 5 (next): local pose model (MoveNet)
Every failed approach used the crude blob. Try MoveNet (tflite-runtime, on-device,
emits keypoints not pixels → privacy-consistent) offline on the run-7 clips: torso
orientation (horizontal vs upright) is the signal the bbox couldn't capture. Expected to
separate sit (upright) from fall (horizontal); will NOT separate fall from deliberate
lie-down (consent-gate territory regardless).

## Decision (provisional)
Trigger on **dropped-low + sustained-stillness** (vertical position + stillness, on a
LOCKED camera), with the consent gate disambiguating couch/crouch. This subsumes the
earlier "sustained stillness / unexpected absence" reframe —
(the robust signal already produced by the Kalman covariance + ABSENT logic + pipeline
baseline), which is the PRD thesis ("deviation from pattern, not diagnosis"). Keep
"possible fall" only as a low-confidence hint to the pipeline, never the sole escalation
reason. Real falls still surface as "went down and stopped moving."
