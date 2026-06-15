#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PID_FILE="traj_logs/download_and_bundle.pid"
LOG_FILE="traj_logs/download_and_bundle.log"

mkdir -p traj_logs

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "Trajectory download is already running: PID ${old_pid}"
    echo "Log: ${LOG_FILE}"
    exit 0
  fi
fi

setsid -f bash -lc 'cd "$1" && echo $$ > "$2" && exec bash scripts/download_and_bundle_trajs.sh >> "$3" 2>&1' _ "$ROOT_DIR" "$PID_FILE" "$LOG_FILE" >/dev/null 2>&1
sleep 2

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
  echo "Started trajectory download: PID ${pid}"
  echo "Log: ${LOG_FILE}"
else
  echo "Failed to start trajectory download. Check ${LOG_FILE}" >&2
  exit 1
fi
