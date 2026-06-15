#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DOWNLOAD_PID_FILE="traj_logs/download_and_bundle.pid"
WATCH_PID_FILE="traj_logs/finalize_watcher.pid"
LOG_FILE="traj_logs/finalize_watcher.log"

mkdir -p traj_logs

if [[ -f "$WATCH_PID_FILE" ]]; then
  old_pid="$(cat "$WATCH_PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "Trajectory finalizer watcher is already running: PID ${old_pid}"
    echo "Log: ${LOG_FILE}"
    exit 0
  fi
fi

setsid -f bash -lc '
  set -u
  root_dir="$1"
  download_pid_file="$2"
  watch_pid_file="$3"
  log_file="$4"
  cd "$root_dir"
  echo $$ > "$watch_pid_file"
  {
    echo "[$(date -Is)] finalizer watcher started"
    download_pid="$(cat "$download_pid_file" 2>/dev/null || true)"
    if [[ -n "$download_pid" ]]; then
      echo "[$(date -Is)] waiting for download PID ${download_pid}"
      while ps -p "$download_pid" >/dev/null 2>&1; do
        sleep 60
      done
    else
      echo "[$(date -Is)] no download PID file found; running finalizer now"
    fi
    echo "[$(date -Is)] running finalize_ready_trajs.sh"
    scripts/finalize_ready_trajs.sh
    echo "[$(date -Is)] running audit_traj_goal.py"
    python3 scripts/audit_traj_goal.py
    echo "[$(date -Is)] finalizer watcher finished"
  } >> "$log_file" 2>&1
' _ "$ROOT_DIR" "$DOWNLOAD_PID_FILE" "$WATCH_PID_FILE" "$LOG_FILE" >/dev/null 2>&1

sleep 2

pid="$(cat "$WATCH_PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
  echo "Started trajectory finalizer watcher: PID ${pid}"
  echo "Log: ${LOG_FILE}"
else
  echo "Failed to start trajectory finalizer watcher. Check ${LOG_FILE}" >&2
  exit 1
fi
