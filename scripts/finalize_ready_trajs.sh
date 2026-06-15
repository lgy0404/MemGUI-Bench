#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p traj_logs docs/trajs

LOCK_DIR="traj_logs/.finalize_ready.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  old_pid="$(cat "${LOCK_DIR}/pid" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "skip finalizer: already running as PID ${old_pid}"
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR"
fi
echo "$$" > "${LOCK_DIR}/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

if [[ -x scripts/import_staged_traj_zips.sh ]]; then
  scripts/import_staged_traj_zips.sh
fi

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

zip_is_complete() {
  local agent_name="$1"
  local zip_path="traj_logs/${agent_name}.zip"
  local aria_path="${zip_path}.aria2"
  local expected_size="${EXPECTED_BYTES[$agent_name]}"

  [[ -f "$zip_path" ]] || return 1
  [[ ! -f "$aria_path" ]] || return 1
  [[ "$(stat -c '%s' "$zip_path")" == "$expected_size" ]]
}

bundle_is_valid() {
  local agent_name="$1"
  local bundle_path="docs/trajs/${agent_name}.json.gz"
  local video_path="docs/trajs/${agent_name}.mp4"

  [[ -f "$bundle_path" && -f "$video_path" ]] || return 1
  python3 scripts/verify_traj_bundles.py "$bundle_path"
}

made_progress=0
for agent_name in "${AGENTS[@]}"; do
  if ! zip_is_complete "$agent_name"; then
    echo "skip ${agent_name}: zip is not complete"
    continue
  fi

  if bundle_is_valid "$agent_name"; then
    echo "ok ${agent_name}: bundle already valid"
    continue
  fi

  echo "bundle ${agent_name}: creating docs/trajs/${agent_name}.json.gz"
  python3 docs/bundle_trajs.py "traj_logs/${agent_name}.zip" \
    --with-screenshots \
    -o "docs/trajs/${agent_name}.json.gz"
  python3 scripts/verify_traj_bundles.py "docs/trajs/${agent_name}.json.gz"
  made_progress=1
done

if [[ "$made_progress" == 1 ]]; then
  python3 scripts/verify_traj_site.py
fi
