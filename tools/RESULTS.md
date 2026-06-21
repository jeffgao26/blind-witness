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

## Decision
Reframe the emergency trigger to **sustained stillness / unexpected prolonged absence**
(the robust signal already produced by the Kalman covariance + ABSENT logic + pipeline
baseline), which is the PRD thesis ("deviation from pattern, not diagnosis"). Keep
"possible fall" only as a low-confidence hint to the pipeline, never the sole escalation
reason. Real falls still surface as "went down and stopped moving."
