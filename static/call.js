/* Emergency media client — one-way live view (MJPEG) + two-way call (WebRTC).
   Connects DIRECTLY to the Pi (window.PI_MEDIA_URL), not through this server. */

const PI = (window.PI_MEDIA_URL || "").replace(/\/$/, "");
const stage   = document.getElementById("media-stage");
const liveImg = document.getElementById("live-img");
const remote  = document.getElementById("remote-video");
const local   = document.getElementById("local-video");
const endBtn  = document.getElementById("end-btn");
const hint    = document.getElementById("media-hint");

let pc = null;
let localStream = null;

function openStage(mode) {
  stage.classList.add("open");
  endBtn.style.display = "inline-block";
  liveImg.style.display   = mode === "live" ? "block" : "none";
  remote.style.display    = mode === "call" ? "block" : "none";
}

// One-way: same-origin /live route (Flask proxies the Pi's consent-gated MJPEG),
// so it renders through the single 5050 tunnel — no second port, no browser LAN grant.
function startLiveView() {
  hint.textContent = "Live view — one way. The room can't see or hear you.";
  liveImg.onerror = () => { hint.textContent = "No live session active yet (consent window may still be open)."; };
  liveImg.src = "/live?t=" + Date.now();
  openStage("live");
}

// Two-way: WebRTC. Family cam+mic <-> Pi cam+mic.
async function startCall() {
  hint.textContent = "Connecting call…";
  try {
    localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
  } catch (e) {
    hint.textContent = "Camera/mic permission denied — can't call.";
    return;
  }
  local.srcObject = localStream;
  local.classList.add("live");
  openStage("call");

  pc = new RTCPeerConnection();
  localStream.getTracks().forEach(t => pc.addTrack(t, localStream));
  pc.ontrack = (ev) => { remote.srcObject = ev.streams[0]; };
  pc.onconnectionstatechange = () => {
    if (pc) hint.textContent = "Call: " + pc.connectionState;
  };

  // Non-trickle: gather all ICE candidates, then send one complete offer.
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await new Promise(res => {
    if (pc.iceGatheringState === "complete") return res();
    const check = () => { if (pc.iceGatheringState === "complete") { pc.removeEventListener("icegatheringstatechange", check); res(); } };
    pc.addEventListener("icegatheringstatechange", check);
    setTimeout(res, 2000); // fallback so we never hang
  });

  try {
    const resp = await fetch(PI + "/call/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type }),
    });
    const answer = await resp.json();
    await pc.setRemoteDescription(answer);
  } catch (e) {
    hint.textContent = "Call failed to reach the device.";
    endMedia();
  }
}

function endMedia() {
  if (pc) { pc.close(); pc = null; }
  if (localStream) { localStream.getTracks().forEach(t => t.stop()); localStream = null; }
  liveImg.src = "";
  remote.srcObject = null;
  local.srcObject = null;
  local.classList.remove("live");
  stage.classList.remove("open");
  endBtn.style.display = "none";
  hint.textContent = "";
}

// If the alert clears, tear any media down.
window.addEventListener("constant:alert-cleared", endMedia);
