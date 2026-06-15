#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PID_FILE="traj_logs/finalize_poller.pid"
LOG_FILE="traj_logs/finalize_poller.log"
INTERVAL_SECONDS="${FINALIZE_POLL_INTERVAL_SECONDS:-600}"

mkdir -p traj_logs

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "Trajectory finalize poller is already running: PID ${old_pid}"
    echo "Log: ${LOG_FILE}"
    exit 0
  fi
fi

setsid -f bash -lc '
  set -u
  root_dir="$1"
  pid_file="$2"
  log_file="$3"
  interval_seconds="$4"
  cd "$root_dir"
  echo $$ > "$pid_file"
  while true; do
    {
      echo "[$(date -Is)] finalize poll"
      scripts/finalize_ready_trajs.sh
      scripts/verify_ready_bundles.sh
    } >> "$log_file" 2>&1
    sleep "$interval_seconds"
  done
' _ "$ROOT_DIR" "$PID_FILE" "$LOG_FILE" "$INTERVAL_SECONDS" >/dev/null 2>&1

sleep 2

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
  echo "Started trajectory finalize poller: PID ${pid}"
  echo "Log: ${LOG_FILE}"
else
  echo "Failed to start trajectory finalize poller. Check ${LOG_FILE}" >&2
  exit 1
fi
