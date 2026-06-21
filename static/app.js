/* Family-view polling + alert flip */

const STATE_LABEL = {
  PRESENT_NORMAL: "All good",
  PRESENT_STILL:  "Resting",
  FALL_SUSPECTED: "Possible fall",
  ABSENT:         "Not in room",
  UNCERTAIN:      "Checking…",
};

const STATE_COLOR = {
  PRESENT_NORMAL: "green",
  PRESENT_STILL:  "amber",
  FALL_SUSPECTED: "red",
  ABSENT:         "gray",
  UNCERTAIN:      "amber",
};

const dot        = document.getElementById("dot");
const stateLabel = document.getElementById("state-label");
const statusText = document.getElementById("status-text");
const durText    = document.getElementById("duration-text");
const alertNote  = document.getElementById("alert-note");
const alarm      = document.getElementById("alarm");

let alarmSilenced = false;
let lastAlertId   = null;

function acknowledge() {
  alarmSilenced = true;
  alarm.pause();
  alarm.currentTime = 0;
}

function fmtDuration(secs) {
  if (!secs) return "";
  const s = Math.round(secs);
  if (s < 60)  return `${s}s`;
  if (s < 3600) return `${Math.floor(s/60)}m ${s%60}s`;
  return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`;
}

async function poll() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    const state   = data.state || "UNCERTAIN";
    const color   = STATE_COLOR[state]  || "gray";
    const label   = STATE_LABEL[state]  || state;
    const active  = data.active_alert;

    // Update indicators
    dot.className        = color;
    stateLabel.textContent  = label;
    stateLabel.className    = color;
    statusText.textContent  = state ? state.replace(/_/g, " ") : "—";
    durText.textContent     = data.duration_in_state ? fmtDuration(data.duration_in_state) : "";

    // Alert flip
    const isAlert = !!active;
    document.body.classList.toggle("alert-active", isAlert);

    if (isAlert) {
      alertNote.textContent = active.family_note || "";
      document.title = "⚠️ ALERT — Constant";

      // Only fire sound on a new alert episode
      if (active.id !== lastAlertId) {
        lastAlertId   = active.id;
        alarmSilenced = false;
      }
      if (!alarmSilenced && alarm.paused) {
        alarm.play().catch(() => {});   // browser may block until first gesture
      }
    } else {
      alertNote.textContent = "";
      document.title        = "Constant";
      alarm.pause();
      alarm.currentTime = 0;
      alarmSilenced = false;
      lastAlertId   = null;
    }
  } catch (_) {}
}

poll();
setInterval(poll, 2000);
