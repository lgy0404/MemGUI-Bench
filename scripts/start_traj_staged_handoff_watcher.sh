#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PID_FILE="traj_logs/staged_handoff.pid"
LOG_FILE="traj_logs/staged_handoff.log"
INTERVAL_SECONDS="${STAGED_HANDOFF_INTERVAL_SECONDS:-10}"

mkdir -p traj_logs

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "Trajectory staged handoff watcher is already running: PID ${old_pid}"
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

  is_complete() {
    local path="$1"
    local expected="$2"
    [[ -f "$path" ]] && [[ ! -f "${path}.aria2" ]] && [[ "$(stat -c "%s" "$path")" == "$expected" ]]
  }

  maybe_handoff() {
    local key="$1"
    local trigger_agent="$2"
    local trigger_size="$3"
    shift 3

    [[ " ${completed_handoffs} " != *" ${key} "* ]] || return 0
    is_complete "traj_logs/${trigger_agent}.zip" "$trigger_size" || return 0

    echo "[$(date -Is)] ${trigger_agent} complete; promoting staged partials for: $*"
    scripts/promote_staged_traj_partials.sh --stop-active "$@"
    completed_handoffs="${completed_handoffs} ${key}"
  }

  {
    echo "[$(date -Is)] staged handoff watcher started"
    completed_handoffs=""
    while true; do
      maybe_handoff after-agent-s2 agent-s2 21203200605 gui-owl-7b m3a
      maybe_handoff after-m3a m3a 21295322173 mobile-agent-e qwen3-vl-8b-instruct
      maybe_handoff after-qwen3 qwen3-vl-8b-instruct 43499068026 t3a

      if [[ " ${completed_handoffs} " == *" after-agent-s2 "* ]] &&
         [[ " ${completed_handoffs} " == *" after-m3a "* ]] &&
         [[ " ${completed_handoffs} " == *" after-qwen3 "* ]]; then
        echo "[$(date -Is)] staged handoff watcher finished"
        break
      fi

      download_pid="$(cat traj_logs/download_and_bundle.pid 2>/dev/null || true)"
      if [[ -n "$download_pid" ]] && ! ps -p "$download_pid" >/dev/null 2>&1; then
        echo "[$(date -Is)] main downloader exited; staged handoff watcher finished"
        break
      fi

      sleep "$interval_seconds"
    done
  } >> "$log_file" 2>&1
' _ "$ROOT_DIR" "$PID_FILE" "$LOG_FILE" "$INTERVAL_SECONDS" >/dev/null 2>&1

sleep 2

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
  echo "Started trajectory staged handoff watcher: PID ${pid}"
  echo "Log: ${LOG_FILE}"
else
  echo "Failed to start trajectory staged handoff watcher. Check ${LOG_FILE}" >&2
  exit 1
fi
