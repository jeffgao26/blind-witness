#!/usr/bin/env bash
# Bring the full Constant pipeline up/down on the Pi.
#   device monitoring_loop -> Redis -> consumer (-> SQLite + alerting) -> Flask webapp
#   + emergency supervisor (consent + camera handoff on a critical alert)
#
# Usage (on the Pi, from the repo root):
#   scripts/run_e2e.sh start     # redis + consumer + monitoring_loop + webapp + supervisor
#   scripts/run_e2e.sh nocam     # everything EXCEPT monitoring_loop (frees the camera)
#   scripts/run_e2e.sh stop
#   scripts/run_e2e.sh status
set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs

# One-way live view uses only stdlib MJPEG + cv2/redis/flask (all system), so plain
# python3 is enough — no aiortc venv needed. (The v2 WebRTC call would need ~/rtcenv.)
PY=python3
export CONSTANT_AUDIO_DEV="${CONSTANT_AUDIO_DEV:-plughw:1,0}"   # touchscreen speaker

start_one() { # name, module
  pkill -f "$2" 2>/dev/null
  nohup "$PY" -m "$2" >"logs/$1.log" 2>&1 &
  echo "  started $1 (pid $!) -> logs/$1.log"
}

ensure_redis() {
  redis-cli ping >/dev/null 2>&1 && { echo "  redis: up"; return; }
  echo "  redis: starting"; sudo systemctl start redis-server 2>/dev/null
}

case "${1:-start}" in
  start|nocam)
    echo "  python: $PY"
    ensure_redis
    start_one consumer   pipeline.consumer
    start_one webapp     pipeline.app
    start_one supervisor emergency.supervisor
    if [ "$1" = "start" ]; then
      start_one monitoring device.monitoring_loop
    else
      echo "  (monitoring_loop NOT started — camera is free)"
    fi
    echo
    echo "webapp:   http://<pi-ip>:5050   (or tunnel:  ssh -L 5050:localhost:5050 ...)"
    echo "logs:     tail -f logs/*.log"
    ;;
  stop)
    for m in device.monitoring_loop emergency.supervisor emergency.call \
             pipeline.consumer pipeline.app; do
      pkill -f "$m" 2>/dev/null && echo "  stopped $m"
    done
    redis-cli del eldercare:camera_yield eldercare:camera_released >/dev/null 2>&1
    ;;
  status)
    for m in "device.monitoring_loop:monitoring" "pipeline.consumer:consumer" \
             "pipeline.app:webapp" "emergency.supervisor:supervisor"; do
      name="${m##*:}"; pat="${m%%:*}"
      n=$(pgrep -f "$pat" | wc -l); echo "  $name: $([ "$n" -gt 0 ] && echo running || echo stopped)"
    done
    echo "  redis stream len: $(redis-cli XLEN eldercare:events 2>/dev/null)"
    echo "  camera_yield flag: $(redis-cli get eldercare:camera_yield 2>/dev/null)"
    ;;
  *) echo "usage: $0 {start|nocam|stop|status}"; exit 1 ;;
esac
