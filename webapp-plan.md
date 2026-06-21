# Constant — Web App Endpoint Build Plan

The family-facing endpoint: **detection → reasoning → alert → notification → UI.**
Device side + Redis ingestion already exist. This plan covers the remaining
pipeline + frontend, built around the *actual* frozen contract.

## Stack decision

- **Backend/UI:** Flask serving server-rendered HTML + vanilla JS (no build step).
- **Notification:** in-app only — full-screen red flip + looping sound + tab-title
  change (`document.title = "⚠️ ALERT"`). No Twilio / push / external services.
- **Reasoning model:** `claude-haiku-4-5-20251001` (cheap + fast for a short
  structured judgment; metered credits). Upgrade to `claude-sonnet-4-6` if quality
  of `family_note` matters in the demo.

## Contract correction (build-plan.md is stale)

Frozen states in `contracts/events.py` are: `PRESENT_NORMAL`, `PRESENT_STILL`,
`FALL_SUSPECTED`, `ABSENT`, `UNCERTAIN`. **Not** `ABSENT_EXPECTED/UNEXPECTED`.
Anomaly set (per `baseline._is_anomalous`) = `{FALL_SUSPECTED, PRESENT_STILL}`.
All web-app work uses these names.

## Data flow

```
monitoring_loop ─XADD─▶ Redis ─▶ consumer.py ─▶ SQLite state_events   (EXISTS)
                                       │
                          on transition INTO anomaly state
                                       ▼
                          reasoning.py ─▶ Claude ─▶ alerts table      (NEW)
                                       │
   app.py (Flask) reads SQLite ────────┘
     /            family.html (status-first)
     /debug       debug.html  (covariance graph + state timeline)
     /api/status  latest state + active alert      ← drives red flip
     /api/events  recent timeline (debug)
     /api/alerts  history + clip links
     /clip/<id>   serve consent video (family view)
                                       │
   family.html + app.js: poll /api/status every 2s
     green / amber / red card; critical → full-screen red + sound + tab title
```

## Alert contract (freeze, like the event contract)

```
alerts:  id, created_ts, trigger_state, severity (info|warning|critical),
         family_note, resolved (0|1), resolved_ts, clip_path (nullable)
```

Lifecycle: created on transition into anomaly state; `resolved=1` when state
returns to `PRESENT_NORMAL`/`ABSENT`. `/api/status` surfaces only the active alert.

## Build order (each step independently testable against fixtures)

1. **`store.py` — add alerts table + helpers** (~20m)
   `init_db` creates `alerts`; add `insert_alert`, `get_active_alert`,
   `resolve_active_alerts`, `get_alerts(limit)`.

2. **`reasoning.py` — Claude call** (~45m)
   Input: `baseline.get_anomaly_context()`. Anthropic SDK with a tool / JSON
   schema → `{severity, family_note, trigger_consent_video}`. Pure function;
   unit-test with a stubbed client.

3. **`consumer.py` — wire transition detection** (~30m)
   Track `last_state`. On `non-anomaly → anomaly` transition: call reasoning,
   `insert_alert`. On `anomaly → normal/absent`: `resolve_active_alerts`.
   Heartbeats of the same state do nothing (no dup alerts, no extra Claude calls).

4. **`app.py` — Flask backend** (~60m)
   Routes above. `/api/status` joins latest event + active alert. `/api/events`
   returns last N for the covariance series. Serve clips read-only from the
   family-view folder.

5. **`family.html` + `static/app.js`** (~60m)
   Status card: green=`PRESENT_NORMAL`/`ABSENT`, amber=`UNCERTAIN`,
   red=active critical alert. On red: full-screen overlay, loop `alert.mp3`,
   set `document.title`. Show `family_note`. Acknowledge button → stop sound.

6. **`debug.html`** (~30m, judges' view)
   Live covariance_trace sparkline, current state + duration, sampling rate,
   raw event timeline. Polls `/api/events`.

7. **Integration + demo polish** (~45m)
   Run `tools/fixtures.py` → consumer → app. Walk: normal (green) → leave frame
   (amber UNCERTAIN) → FALL_SUSPECTED (red + sound + Claude note) → resolve.

## Verification checklist

- [ ] Fixture replay drives the family page green → amber → red without touching CV
- [ ] Claude called exactly once per anomaly episode (not per heartbeat)
- [ ] Duplicate anomaly heartbeats do not create duplicate alerts
- [ ] Returning to `PRESENT_NORMAL` auto-resolves the alert; page returns to green
- [ ] `/api/status` never exposes video; `/clip` only serves from the consent folder
- [ ] Red flip changes the browser tab title even when the tab is backgrounded

## Defer / out of scope for endpoint

- SMS/voice/web-push (in-app sound only for now)
- SSE/WebSocket (2s polling is enough and more reliable for the demo)
- Auth / multi-family accounts
- Learned baseline (still seeded)
