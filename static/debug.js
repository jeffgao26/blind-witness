/* Debug dashboard — sparkline + events table */

const STATE_COLOR = {
  PRESENT_NORMAL: "#30d158",
  PRESENT_STILL:  "#ffd60a",
  FALL_SUSPECTED: "#ff3b3b",
  ABSENT:         "#555",
  UNCERTAIN:      "#af8bff",
};

async function refresh() {
  try {
    const [status, evRes] = await Promise.all([
      fetch("/api/status").then(r => r.json()),
      fetch("/api/events?limit=60").then(r => r.json()),
    ]);

    // Current state row
    const s = status;
    document.getElementById("d-state").textContent = s.state || "—";
    document.getElementById("d-state").className   = "v state-" + (s.state || "");
    document.getElementById("d-zone").textContent  = s.zone  || "—";
    document.getElementById("d-dur").textContent   = s.duration_in_state != null
      ? s.duration_in_state.toFixed(1) + "s" : "—";
    document.getElementById("d-cov").textContent   = s.covariance_trace != null
      ? s.covariance_trace.toFixed(1) : "—";
    document.getElementById("d-ts").textContent    = s.ts
      ? new Date(s.ts * 1000).toLocaleTimeString() : "—";

    // Sparkline
    drawSparkline(evRes);

    // Events table
    const tbody = document.getElementById("events-tbody");
    tbody.innerHTML = "";
    const rows = [...evRes].reverse();
    for (const ev of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${new Date(ev.timestamp * 1000).toLocaleTimeString()}</td>
        <td class="state-${ev.state}">${ev.state}</td>
        <td>${ev.duration_in_state.toFixed(1)}</td>
        <td>${ev.covariance_trace.toFixed(1)}</td>
        <td>${ev.zone}</td>`;
      tbody.appendChild(tr);
    }
  } catch (_) {}
}

function drawSparkline(events) {
  const canvas = document.getElementById("sparkline");
  const ctx    = canvas.getContext("2d");
  const W      = canvas.width;
  const H      = canvas.height;
  ctx.clearRect(0, 0, W, H);

  if (!events.length) return;

  const vals = events.map(e => e.covariance_trace);
  const min  = Math.min(...vals);
  const max  = Math.max(...vals) || 1;
  const pad  = 6;

  // Grid line at max
  ctx.strokeStyle = "#1e1e1e";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, pad);
  ctx.lineTo(W, pad);
  ctx.stroke();

  // Sparkline
  ctx.beginPath();
  ctx.strokeStyle = "#af8bff";
  ctx.lineWidth = 1.5;
  vals.forEach((v, i) => {
    const x = (i / (vals.length - 1 || 1)) * W;
    const y = pad + (1 - (v - min) / (max - min + 0.001)) * (H - 2 * pad);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // State-colored dots
  events.forEach((ev, i) => {
    const x   = (i / (vals.length - 1 || 1)) * W;
    const v   = ev.covariance_trace;
    const y   = pad + (1 - (v - min) / (max - min + 0.001)) * (H - 2 * pad);
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, 2 * Math.PI);
    ctx.fillStyle = STATE_COLOR[ev.state] || "#555";
    ctx.fill();
  });
}

refresh();
setInterval(refresh, 2000);
