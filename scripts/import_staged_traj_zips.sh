#!/usr/bin/env bash

set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p traj_logs

LOCK_DIR="traj_logs/.import_staged.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  old_pid="$(cat "${LOCK_DIR}/pid" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "skip import: already running as PID ${old_pid}"
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
fi
echo "$$" > "${LOCK_DIR}/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

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

if [[ "$#" -gt 0 ]]; then
  AGENTS=("$@")
fi

zip_is_complete_at() {
  local zip_path="$1"
  local expected_size="$2"

  [[ -f "$zip_path" ]] || return 1
  [[ ! -f "${zip_path}.aria2" ]] || return 1
  [[ "$(stat -c '%s' "$zip_path")" == "$expected_size" ]]
}

root_download_is_active() {
  local agent_name="$1"

  pgrep -f -- "--local-dir traj_logs --include ${agent_name}.zip" >/dev/null 2>&1
}

stamp="$(date +%Y%m%d_%H%M%S)"
made_progress=0

for agent_name in "${AGENTS[@]}"; do
  expected_size="${EXPECTED_BYTES[$agent_name]:-}"
  if [[ -z "$expected_size" ]]; then
    echo "skip ${agent_name}: unknown expected size" >&2
    continue
  fi

  root_zip="traj_logs/${agent_name}.zip"
  staged_zip="traj_logs/_parallel_downloads/${agent_name}/${agent_name}.zip"

  if zip_is_complete_at "$root_zip" "$expected_size"; then
    echo "ok ${agent_name}: root zip already complete"
    continue
  fi

  if ! zip_is_complete_at "$staged_zip" "$expected_size"; then
    echo "skip ${agent_name}: no complete staged zip"
    continue
  fi

  if [[ -f "${root_zip}.aria2" ]] && root_download_is_active "$agent_name"; then
    echo "skip ${agent_name}: root download is currently active"
    continue
  fi

  backup_dir="traj_logs/_replaced_partials_${stamp}"
  mkdir -p "$backup_dir"

  if [[ -f "$root_zip" ]]; then
    mv "$root_zip" "${backup_dir}/${agent_name}.zip"
  fi
  if [[ -f "${root_zip}.aria2" ]]; then
    mv "${root_zip}.aria2" "${backup_dir}/${agent_name}.zip.aria2"
  fi

  mv "$staged_zip" "$root_zip"
  echo "imported ${agent_name}: staged zip -> ${root_zip}"
  made_progress=1
done

exit 0
