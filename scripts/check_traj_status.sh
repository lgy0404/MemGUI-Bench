#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

AGENTS=(
  agent-s2
  gui-owl-7b
  m3a
  mobile-agent-e
  qwen3-vl-8b-instruct
  t3a
)

declare -A EXPECTED_BYTES=(
  [agent-s2]=21203200605
  [gui-owl-7b]=32089648797
  [m3a]=21295322173
  [mobile-agent-e]=25785494378
  [qwen3-vl-8b-instruct]=43499068026
  [t3a]=22437818031
)

format_bytes() {
  python3 - "$1" <<'PY'
import sys

value = int(sys.argv[1])
units = ["B", "K", "M", "G", "T"]
size = float(value)
unit = units[0]
for unit in units:
    if size < 1024 or unit == units[-1]:
        break
    size /= 1024
if unit == "B":
    print(f"{int(size)}{unit}")
elif size >= 10:
    print(f"{size:.0f}{unit}")
else:
    print(f"{size:.1f}{unit}")
PY
}

printf '%-24s %-12s %-12s %-12s %-8s %-12s %-12s\n' "agent" "zip" "downloaded" "total" "pct" "extracted" "bundle"
printf '%-24s %-12s %-12s %-12s %-8s %-12s %-12s\n' "-----" "---" "----------" "-----" "---" "---------" "------"

for agent in "${AGENTS[@]}"; do
  zip_path="traj_logs/${agent}.zip"
  aria_path="${zip_path}.aria2"
  extract_marker="traj_logs/${agent}/.extract_complete"
  bundle_path="docs/trajs/${agent}.json.gz"
  video_path="docs/trajs/${agent}.mp4"

  if [[ -f "$zip_path" ]]; then
    zip_state="$([[ -f "$aria_path" ]] && echo partial || echo present)"
    downloaded="$(du -h "$zip_path" | awk '{print $1}')"
    expected_bytes="${EXPECTED_BYTES[$agent]:-0}"
    if [[ "$expected_bytes" -gt 0 ]]; then
      total="$(format_bytes "$expected_bytes")"
    else
      total="$(ls -lh "$zip_path" | awk '{print $5}')"
    fi
    pct="$(python3 - "$zip_path" "$expected_bytes" <<'PY'
import os
import sys
path = sys.argv[1]
expected = int(sys.argv[2])
st = os.stat(path)
downloaded = st.st_blocks * 512
total = expected if expected > 0 else st.st_size
if total > 0:
    print(f"{min(downloaded / total * 100, 100):.1f}%")
else:
    print("-")
PY
)"
  else
    zip_state="missing"
    downloaded="-"
    expected_bytes="${EXPECTED_BYTES[$agent]:-0}"
    if [[ "$expected_bytes" -gt 0 ]]; then
      total="$(format_bytes "$expected_bytes")"
      pct="0.0%"
    else
      total="-"
      pct="-"
    fi
  fi

  extracted="$([[ -f "$extract_marker" ]] && echo yes || echo no)"
  if [[ -f "$bundle_path" && -f "$video_path" ]]; then
    bundle="yes"
  elif [[ -f "$bundle_path" ]]; then
    bundle="json-only"
  else
    bundle="no"
  fi

  printf '%-24s %-12s %-12s %-12s %-8s %-12s %-12s\n' "$agent" "$zip_state" "$downloaded" "$total" "$pct" "$extracted" "$bundle"
done

if compgen -G "traj_logs/_bad_partials_*" >/dev/null; then
  echo
  echo "quarantined partials:"
  find traj_logs -maxdepth 1 -type d -name '_bad_partials_*' -printf '  %p\n' | sort
fi

if compgen -G "traj_logs/_parallel_downloads/*/*.zip" >/dev/null; then
  echo
  echo "parallel staged downloads:"
  printf '  %-24s %-12s %-12s %-8s\n' "agent" "state" "downloaded" "pct"
  for agent in "${AGENTS[@]}"; do
    stage_zip="traj_logs/_parallel_downloads/${agent}/${agent}.zip"
    stage_aria="${stage_zip}.aria2"
    [[ -f "$stage_zip" ]] || continue
    stage_state="$([[ -f "$stage_aria" ]] && echo partial || echo present)"
    stage_downloaded="$(du -h "$stage_zip" | awk '{print $1}')"
    expected_bytes="${EXPECTED_BYTES[$agent]:-0}"
    stage_pct="$(python3 - "$stage_zip" "$expected_bytes" <<'PY'
import os
import sys
path = sys.argv[1]
expected = int(sys.argv[2])
st = os.stat(path)
downloaded = st.st_blocks * 512
total = expected if expected > 0 else st.st_size
if total > 0:
    print(f"{min(downloaded / total * 100, 100):.1f}%")
else:
    print("-")
PY
)"
    printf '  %-24s %-12s %-12s %-8s\n' "$agent" "$stage_state" "$stage_downloaded" "$stage_pct"
  done
fi

if [[ -f traj_logs/download_and_bundle.pid ]] && ps -p "$(cat traj_logs/download_and_bundle.pid)" >/dev/null 2>&1; then
  echo
  echo "running: PID $(cat traj_logs/download_and_bundle.pid)"
else
  echo
  echo "running: no"
fi

if [[ -f traj_logs/finalize_watcher.pid ]] && ps -p "$(cat traj_logs/finalize_watcher.pid)" >/dev/null 2>&1; then
  echo "finalizer watcher: PID $(cat traj_logs/finalize_watcher.pid)"
else
  echo "finalizer watcher: no"
fi

if [[ -f traj_logs/parallel_stage.pid ]] && ps -p "$(cat traj_logs/parallel_stage.pid)" >/dev/null 2>&1; then
  echo "parallel stage: PID $(cat traj_logs/parallel_stage.pid)"
else
  echo "parallel stage: no"
fi

for extra_parallel_pid_file in traj_logs/parallel_stage_*.pid; do
  [[ -e "$extra_parallel_pid_file" ]] || continue
  [[ "$extra_parallel_pid_file" != *_supervisor.pid ]] || continue
  extra_name="${extra_parallel_pid_file##*/parallel_stage_}"
  extra_name="${extra_name%.pid}"
  if ps -p "$(cat "$extra_parallel_pid_file")" >/dev/null 2>&1; then
    echo "parallel stage ${extra_name}: PID $(cat "$extra_parallel_pid_file")"
  else
    echo "parallel stage ${extra_name}: no"
  fi
done

for named_stage_supervisor_pid_file in traj_logs/parallel_stage_*_supervisor.pid; do
  [[ -e "$named_stage_supervisor_pid_file" ]] || continue
  supervisor_name="${named_stage_supervisor_pid_file##*/parallel_stage_}"
  supervisor_name="${supervisor_name%_supervisor.pid}"
  if ps -p "$(cat "$named_stage_supervisor_pid_file")" >/dev/null 2>&1; then
    echo "parallel stage ${supervisor_name} supervisor: PID $(cat "$named_stage_supervisor_pid_file")"
  else
    echo "parallel stage ${supervisor_name} supervisor: no"
  fi
done

if [[ -f traj_logs/finalize_poller.pid ]] && ps -p "$(cat traj_logs/finalize_poller.pid)" >/dev/null 2>&1; then
  echo "finalize poller: PID $(cat traj_logs/finalize_poller.pid)"
else
  echo "finalize poller: no"
fi

if [[ -f traj_logs/staged_handoff.pid ]] && ps -p "$(cat traj_logs/staged_handoff.pid)" >/dev/null 2>&1; then
  echo "staged handoff: PID $(cat traj_logs/staged_handoff.pid)"
else
  echo "staged handoff: no"
fi

if [[ -f traj_logs/download_supervisor.pid ]] && ps -p "$(cat traj_logs/download_supervisor.pid)" >/dev/null 2>&1; then
  echo "download supervisor: PID $(cat traj_logs/download_supervisor.pid)"
else
  echo "download supervisor: no"
fi
