#!/usr/bin/env bash

set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p traj_logs

LOCK_DIR="traj_logs/.promote_staged.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  old_pid="$(cat "${LOCK_DIR}/pid" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "skip promote: already running as PID ${old_pid}"
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
fi
echo "$$" > "${LOCK_DIR}/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

STOP_ACTIVE=0
if [[ "${1:-}" == "--stop-active" ]]; then
  STOP_ACTIVE=1
  shift
fi

AGENTS=(
  gui-owl-7b
  m3a
  mobile-agent-e
  qwen3-vl-8b-instruct
  t3a
)

if [[ "$#" -gt 0 ]]; then
  AGENTS=("$@")
fi

downloaded_bytes() {
  local path="$1"

  if [[ -f "$path" ]]; then
    python3 - "$path" <<'PY'
import os
import sys
print(os.stat(sys.argv[1]).st_blocks * 512)
PY
  else
    echo 0
  fi
}

root_download_is_active() {
  local agent_name="$1"

  pgrep -f -- "--local-dir traj_logs --include ${agent_name}.zip" >/dev/null 2>&1
}

staged_download_pids() {
  local agent_name="$1"
  local stage_dir="${ROOT_DIR}/traj_logs/_parallel_downloads/${agent_name}"
  local parallel_stage_pid
  local proc
  local pid
  local ppid
  local cwd
  local cmd

  parallel_stage_pid="$(cat traj_logs/parallel_stage.pid 2>/dev/null || true)"
  {
    pgrep -f -- "_parallel_downloads/${agent_name}.*${agent_name}\\.zip" || true
    for proc in /proc/[0-9]*; do
      pid="${proc##*/}"
      cwd="$(readlink -f "${proc}/cwd" 2>/dev/null || true)"
      if [[ "$cwd" == "$stage_dir" ]]; then
        echo "$pid"
      fi
    done
  } | while read -r pid; do
    [[ -n "$pid" ]] || continue
    echo "$pid"

    # Include the per-agent worker shell so an already-running staged downloader
    # cannot restart this same agent after handoff. Keep the top-level parallel
    # stage process alive so it can continue with later agents.
    while [[ -r "/proc/${pid}/stat" ]]; do
      ppid="$(awk '{print $4}' "/proc/${pid}/stat" 2>/dev/null || true)"
      [[ -n "$ppid" && "$ppid" != "1" ]] || break
      [[ -z "$parallel_stage_pid" || "$ppid" != "$parallel_stage_pid" ]] || break
      cmd="$(tr '\0' ' ' < "/proc/${ppid}/cmdline" 2>/dev/null || true)"
      if [[ "$cmd" == *"parallel_stage_traj_downloads.sh"* ]]; then
        echo "$ppid"
        pid="$ppid"
        continue
      fi
      break
    done
  done | sort -u
}

stop_staged_download() {
  local agent_name="$1"
  local pids
  local waited

  pids="$(staged_download_pids "$agent_name" | tr '\n' ' ')"
  [[ -n "$pids" ]] || return 0

  echo "stop ${agent_name}: staged download PIDs ${pids}"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true

  for waited in $(seq 1 30); do
    if [[ -z "$(staged_download_pids "$agent_name" | tr '\n' ' ')" ]]; then
      return 0
    fi
    sleep 1
  done

  echo "skip ${agent_name}: staged download did not stop cleanly" >&2
  return 1
}

stamp="$(date +%Y%m%d_%H%M%S)"

for agent_name in "${AGENTS[@]}"; do
  root_zip="traj_logs/${agent_name}.zip"
  root_aria="${root_zip}.aria2"
  staged_zip="traj_logs/_parallel_downloads/${agent_name}/${agent_name}.zip"
  staged_aria="${staged_zip}.aria2"
  promoted_marker="traj_logs/_parallel_downloads/${agent_name}/.promoted_to_root"

  if [[ ! -f "$staged_zip" ]]; then
    echo "skip ${agent_name}: no staged partial"
    continue
  fi

  if root_download_is_active "$agent_name"; then
    echo "skip ${agent_name}: root download is active"
    continue
  fi

  staged_active=0
  if [[ -n "$(staged_download_pids "$agent_name" | tr '\n' ' ')" ]]; then
    staged_active=1
  fi

  if [[ "$staged_active" == 1 ]]; then
    if [[ "$STOP_ACTIVE" == 1 ]]; then
      stop_staged_download "$agent_name" || continue
    else
      echo "skip ${agent_name}: staged download is active"
      continue
    fi
  fi

  if [[ -f "$staged_aria" ]]; then
    staged_state="partial"
  else
    staged_state="present"
  fi

  root_downloaded="$(downloaded_bytes "$root_zip")"
  staged_downloaded="$(downloaded_bytes "$staged_zip")"
  if [[ "$staged_downloaded" -le "$root_downloaded" ]]; then
    echo "skip ${agent_name}: root partial is at least as large (${root_downloaded} >= ${staged_downloaded})"
    continue
  fi

  backup_dir="traj_logs/_replaced_partials_${stamp}"
  mkdir -p "$backup_dir"

  if [[ -f "$root_zip" ]]; then
    mv "$root_zip" "${backup_dir}/${agent_name}.zip"
  fi
  if [[ -f "$root_aria" ]]; then
    mv "$root_aria" "${backup_dir}/${agent_name}.zip.aria2"
  fi

  mv "$staged_zip" "$root_zip"
  if [[ -f "$staged_aria" ]]; then
    mv "$staged_aria" "$root_aria"
  fi
  printf '%s\n' "$(date -Is)" > "$promoted_marker"

  echo "promoted ${agent_name}: ${staged_state} staged partial (${staged_downloaded} bytes) -> ${root_zip}"
done
