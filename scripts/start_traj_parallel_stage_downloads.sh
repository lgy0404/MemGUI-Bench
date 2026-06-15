#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -n "${PARALLEL_STAGE_NAME:-}" ]]; then
  safe_name="${PARALLEL_STAGE_NAME//[^A-Za-z0-9_.-]/_}"
  PID_FILE="traj_logs/parallel_stage_${safe_name}.pid"
  LOG_FILE="traj_logs/parallel_stage_${safe_name}.log"
  LOCK_DIR="traj_logs/.parallel_stage_${safe_name}.lock"
else
  PID_FILE="traj_logs/parallel_stage.pid"
  LOG_FILE="traj_logs/parallel_stage.log"
  LOCK_DIR="traj_logs/.parallel_stage.lock"
fi
TARGET_ARGS=("$@")

mkdir -p traj_logs

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "Parallel staged trajectory download is already running: PID ${old_pid}"
    echo "Log: ${LOG_FILE}"
    exit 0
  fi
fi

setsid -f bash -lc '
  root_dir="$1"
  pid_file="$2"
  log_file="$3"
  lock_dir="$4"
  shift 4
  cd "$root_dir"
  echo $$ > "$pid_file"
  export PARALLEL_STAGE_LOCK_DIR="$lock_dir"
  exec bash scripts/parallel_stage_traj_downloads.sh "$@" >> "$log_file" 2>&1
' _ "$ROOT_DIR" "$PID_FILE" "$LOG_FILE" "$LOCK_DIR" "${TARGET_ARGS[@]}" >/dev/null 2>&1
sleep 2

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
  echo "Started parallel staged trajectory download: PID ${pid}"
  echo "Log: ${LOG_FILE}"
else
  echo "Failed to start parallel staged trajectory download. Check ${LOG_FILE}" >&2
  exit 1
fi
