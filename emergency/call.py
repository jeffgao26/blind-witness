"""Emergency media server — one-way live view AND two-way call, one shared camera.

  >>> Still structurally isolated: imports cv2 / aiortc / aiohttp / stdlib, NOTHING
  >>> from device/. The monitoring loop has no path here. This server only runs once
  >>> the consent sequence (emergency/consent_video.py) has lapsed.

Endpoints (port 8090), connected to DIRECTLY by the family browser on the LAN:
  GET  /emergency    one-way MJPEG live view (room only; family can't be seen/heard)
  POST /call/offer   WebRTC: Pi camera + mic out, family audio played on the Pi speaker
  OPTIONS /call/offer  CORS preflight (the family page is served from a different origin)

Run on the Pi (needs the aiortc venv):  ~/rtcenv/bin/python -m emergency.call
Env: CONSTANT_MIC (alsa, default "hw:3,0"), CONSTANT_AUDIO_DEV (speaker, default "plughw:1,0")
"""
import asyncio
import json
import os
import subprocess
import threading
import time

import cv2
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaBlackhole, MediaPlayer
from av import AudioResampler, VideoFrame

W, H, FPS = 640, 480, 15
PORT = 8090
MIC = os.environ.get("CONSTANT_MIC", "hw:3,0")
SPK = os.environ.get("CONSTANT_AUDIO_DEV", "plughw:1,0")
CORS = {"Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"}

_latest = {"frame": None}
_lock = threading.Lock()
_pcs = set()


def _grab_loop():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    while True:
        ok, frame = cap.read()
        if ok:
            with _lock:
                _latest["frame"] = frame   # in memory only; never written to disk


class CameraTrack(VideoStreamTrack):
    """Feeds the shared camera frames into the WebRTC video track."""
    async def recv(self):
        pts, time_base = await self.next_timestamp()
        with _lock:
            f = _latest["frame"]
        if f is None:
            f = np.zeros((H, W, 3), np.uint8)
        vf = VideoFrame.from_ndarray(f, format="bgr24")
        vf.pts, vf.time_base = pts, time_base
        return vf


async def _play_to_speaker(track):
    """Play the family's incoming audio on the Pi speaker via aplay (no extra deps)."""
    resampler = AudioResampler(format="s16", layout="mono", rate=48000)
    proc = subprocess.Popen(["aplay", "-q", "-f", "S16_LE", "-r", "48000", "-c", "1",
                             "-D", SPK], stdin=subprocess.PIPE)
    try:
        while True:
            frame = await track.recv()
            for r in resampler.resample(frame):
                proc.stdin.write(bytes(r.to_ndarray().tobytes()))
    except Exception:
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass


async def offer(request):
    params = await request.json()
    pc = RTCPeerConnection()
    _pcs.add(pc)

    pc.addTrack(CameraTrack())
    mic = None
    try:
        mic = MediaPlayer(MIC, format="alsa")
        if mic.audio:
            pc.addTrack(mic.audio)
    except Exception as e:
        print(f"[call] mic unavailable ({e}); video-only")

    blackhole = MediaBlackhole()

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            asyncio.ensure_future(_play_to_speaker(track))   # family voice -> Pi speaker
        else:
            blackhole.addTrack(track)                        # discard family video

    @pc.on("connectionstatechange")
    async def on_state():
        print(f"[call] connection: {pc.connectionState}")
        if pc.connectionState in ("failed", "closed"):
            await pc.close()
            _pcs.discard(pc)

    await pc.setRemoteDescription(RTCSessionDescription(params["sdp"], params["type"]))
    await blackhole.start()
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return web.json_response(
        {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}, headers=CORS)


async def cors_preflight(request):
    return web.Response(headers=CORS)


async def mjpeg(request):
    resp = web.StreamResponse(headers={
        "Content-Type": "multipart/x-mixed-replace; boundary=frame", **CORS})
    await resp.prepare(request)
    try:
        while True:
            with _lock:
                f = _latest["frame"]
            if f is not None:
                ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    jpeg = buf.tobytes()
                    await resp.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                     + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                                     + jpeg + b"\r\n")
            await asyncio.sleep(1 / FPS)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    return resp


async def on_shutdown(app):
    for pc in list(_pcs):
        await pc.close()
    _pcs.clear()


def main():
    threading.Thread(target=_grab_loop, daemon=True).start()
    time.sleep(1.0)  # let the camera warm up
    app = web.Application()
    app.router.add_get("/emergency", mjpeg)
    app.router.add_post("/call/offer", offer)
    app.router.add_options("/call/offer", cors_preflight)
    app.on_shutdown.append(on_shutdown)
    print(f"[call] emergency media server on :{PORT}  (/emergency mjpeg, /call/offer webrtc)")
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)


if __name__ == "__main__":
    main()
