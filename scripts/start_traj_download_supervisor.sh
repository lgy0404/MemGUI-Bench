#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PID_FILE="traj_logs/download_supervisor.pid"
LOG_FILE="traj_logs/download_supervisor.log"
INTERVAL_SECONDS="${TRAJ_SUPERVISOR_INTERVAL_SECONDS:-900}"

mkdir -p traj_logs

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "Trajectory download supervisor is already running: PID ${old_pid}"
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

  is_running() {
    local pid_file="$1"
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1
  }

  {
    echo "[$(date -Is)] trajectory download supervisor started"
    while true; do
      echo "[$(date -Is)] supervisor status snapshot"
      scripts/check_traj_status.sh

      if python3 scripts/audit_traj_goal.py >/tmp/memgui_traj_supervisor_audit.log 2>&1; then
        cat /tmp/memgui_traj_supervisor_audit.log
        echo "[$(date -Is)] trajectory goal audit passed; supervisor exiting"
        break
      fi

      if ! is_running traj_logs/download_and_bundle.pid; then
        echo "[$(date -Is)] main downloader is not running; running safe finalize scan"
        scripts/finalize_ready_trajs.sh
        echo "[$(date -Is)] restarting main downloader"
        scripts/start_traj_download.sh
      fi

      if ! is_running traj_logs/finalize_poller.pid; then
        echo "[$(date -Is)] restarting finalize poller"
        scripts/start_traj_finalize_poller.sh
      fi

      if ! is_running traj_logs/finalize_watcher.pid; then
        echo "[$(date -Is)] restarting finalize watcher"
        scripts/start_traj_finalize_watcher.sh
      fi

      if ! is_running traj_logs/staged_handoff.pid; then
        echo "[$(date -Is)] restarting staged handoff watcher"
        scripts/start_traj_staged_handoff_watcher.sh
      fi

      if ! is_running traj_logs/parallel_stage.pid; then
        echo "[$(date -Is)] restarting staged parallel downloader"
        scripts/start_traj_parallel_stage_downloads.sh
      fi

      sleep "$interval_seconds"
    done
  } >> "$log_file" 2>&1
' _ "$ROOT_DIR" "$PID_FILE" "$LOG_FILE" "$INTERVAL_SECONDS" >/dev/null 2>&1

sleep 2

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
  echo "Started trajectory download supervisor: PID ${pid}"
  echo "Log: ${LOG_FILE}"
else
  echo "Failed to start trajectory download supervisor. Check ${LOG_FILE}" >&2
  exit 1
fi
