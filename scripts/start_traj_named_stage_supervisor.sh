#!/usr/bin/env bash

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$#" -lt 2 ]]; then
  echo "Usage: $0 <stage-name> <agent> [agent...]" >&2
  exit 2
fi

STAGE_NAME="$1"
shift
TARGET_ARGS=("$@")
SAFE_NAME="${STAGE_NAME//[^A-Za-z0-9_.-]/_}"
PID_FILE="traj_logs/parallel_stage_${SAFE_NAME}_supervisor.pid"
LOG_FILE="traj_logs/parallel_stage_${SAFE_NAME}_supervisor.log"
INTERVAL_SECONDS="${NAMED_STAGE_SUPERVISOR_INTERVAL_SECONDS:-600}"

mkdir -p traj_logs

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "Named staged trajectory supervisor is already running: PID ${old_pid}"
    echo "Log: ${LOG_FILE}"
    exit 0
  fi
fi

setsid -f bash -lc '
  set -u
  root_dir="$1"
  safe_name="$2"
  pid_file="$3"
  log_file="$4"
  interval_seconds="$5"
  shift 5
  targets=("$@")
  cd "$root_dir"
  echo $$ > "$pid_file"

  declare -A expected_bytes=(
    [agent-s2]=21203200605
    [gui-owl-7b]=32089648797
    [m3a]=21295322173
    [mobile-agent-e]=25785494378
    [qwen3-vl-8b-instruct]=43499068026
    [t3a]=22437818031
  )

  is_running() {
    local pid_file="$1"
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1
  }

  root_zip_complete() {
    local agent="$1"
    local zip_path="traj_logs/${agent}.zip"
    local expected="${expected_bytes[$agent]:-}"
    [[ -n "$expected" ]] &&
      [[ -f "$zip_path" ]] &&
      [[ ! -f "${zip_path}.aria2" ]] &&
      [[ "$(stat -c "%s" "$zip_path")" == "$expected" ]]
  }

  targets_complete() {
    local agent
    for agent in "${targets[@]}"; do
      root_zip_complete "$agent" || return 1
    done
    return 0
  }

  {
    echo "[$(date -Is)] named staged supervisor started for ${safe_name}: ${targets[*]}"
    while true; do
      if targets_complete; then
        echo "[$(date -Is)] all targets complete; named staged supervisor exiting"
        break
      fi

      if python3 scripts/audit_traj_goal.py >/tmp/memgui_traj_named_stage_audit_${safe_name}.log 2>&1; then
        cat "/tmp/memgui_traj_named_stage_audit_${safe_name}.log"
        echo "[$(date -Is)] trajectory goal audit passed; named staged supervisor exiting"
        break
      fi

      stage_pid_file="traj_logs/parallel_stage_${safe_name}.pid"
      if ! is_running "$stage_pid_file"; then
        echo "[$(date -Is)] restarting named stage ${safe_name}"
        PARALLEL_STAGE_NAME="$safe_name" scripts/start_traj_parallel_stage_downloads.sh "${targets[@]}"
      fi

      sleep "$interval_seconds"
    done
  } >> "$log_file" 2>&1
' _ "$ROOT_DIR" "$SAFE_NAME" "$PID_FILE" "$LOG_FILE" "$INTERVAL_SECONDS" "${TARGET_ARGS[@]}" >/dev/null 2>&1

sleep 2

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
  echo "Started named staged trajectory supervisor: PID ${pid}"
  echo "Log: ${LOG_FILE}"
else
  echo "Failed to start named staged trajectory supervisor. Check ${LOG_FILE}" >&2
  exit 1
fi
