#!/usr/bin/env bash

set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
HFD="${HFD:-/tmp/hfd.sh}"

if [[ ! -x "$HFD" ]]; then
  if ! curl -L "https://hf-mirror.com/hfd/hfd.sh" -o "$HFD"; then
    echo "Failed to download hfd.sh" >&2
    exit 1
  fi
  chmod +x "$HFD"
fi

mkdir -p traj_logs/_parallel_downloads traj_logs/_parallel_logs

LOCK_DIR="${PARALLEL_STAGE_LOCK_DIR:-traj_logs/.parallel_stage.lock}"
if [[ -d "$LOCK_DIR" ]]; then
  old_pid="$(cat "${LOCK_DIR}/pid" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && ps -p "$old_pid" >/dev/null 2>&1; then
    echo "parallel staged trajectory download is already running: PID ${old_pid}"
    exit 0
  fi
  rm -rf "$LOCK_DIR"
fi

mkdir "$LOCK_DIR"
echo "$$" > "${LOCK_DIR}/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

DEFAULT_AGENTS=(
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
  TARGET_AGENTS=("$@")
else
  TARGET_AGENTS=("${DEFAULT_AGENTS[@]}")
fi

STAGE_HFD_THREADS="${STAGE_HFD_THREADS:-8}"
STAGE_HFD_JOBS="${STAGE_HFD_JOBS:-1}"
STAGE_DOWNLOAD_ATTEMPTS="${STAGE_DOWNLOAD_ATTEMPTS:-30}"
MAX_PARALLEL_STAGE_DOWNLOADS="${MAX_PARALLEL_STAGE_DOWNLOADS:-2}"

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

stage_download_is_active() {
  local agent_name="$1"
  local stage_dir="${ROOT_DIR}/traj_logs/_parallel_downloads/${agent_name}"
  local proc
  local cwd

  if pgrep -f -- "_parallel_downloads/${agent_name}.*${agent_name}\\.zip" >/dev/null 2>&1; then
    return 0
  fi

  for proc in /proc/[0-9]*; do
    cwd="$(readlink -f "${proc}/cwd" 2>/dev/null || true)"
    if [[ "$cwd" == "$stage_dir" ]]; then
      return 0
    fi
  done

  return 1
}

download_agent() {
  local agent_name="$1"
  local zip_name="${agent_name}.zip"
  local expected_size="${EXPECTED_BYTES[$agent_name]:-}"
  local root_zip="traj_logs/${zip_name}"
  local stage_dir="traj_logs/_parallel_downloads/${agent_name}"
  local staged_zip="${stage_dir}/${zip_name}"
  local promoted_marker="${stage_dir}/.promoted_to_root"
  local attempt

  if [[ -z "$expected_size" ]]; then
    echo "skip ${agent_name}: unknown expected size" >&2
    return 1
  fi

  mkdir -p "$stage_dir"

  if [[ -f "$promoted_marker" ]]; then
    echo "ok ${agent_name}: staged partial already promoted to root"
    return 0
  fi

  if zip_is_complete_at "$root_zip" "$expected_size"; then
    echo "ok ${agent_name}: root zip already complete"
    return 0
  fi

  if root_download_is_active "$agent_name"; then
    echo "skip ${agent_name}: root download is active"
    return 0
  fi

  if stage_download_is_active "$agent_name"; then
    echo "skip ${agent_name}: staged download is already active"
    return 0
  fi

  if zip_is_complete_at "$staged_zip" "$expected_size"; then
    scripts/import_staged_traj_zips.sh "$agent_name"
    return 0
  fi

  for ((attempt = 1; attempt <= STAGE_DOWNLOAD_ATTEMPTS; attempt++)); do
    if root_download_is_active "$agent_name"; then
      echo "skip ${agent_name}: root download became active"
      return 0
    fi

    if stage_download_is_active "$agent_name"; then
      echo "skip ${agent_name}: staged download became active"
      return 0
    fi

    if [[ -f "$promoted_marker" ]]; then
      echo "ok ${agent_name}: staged partial promoted to root"
      return 0
    fi

    echo "[$(date -Is)] staging ${zip_name} (attempt ${attempt}/${STAGE_DOWNLOAD_ATTEMPTS})"
    rm -f "${stage_dir}/.hfd/aria2c_urls.txt" "${stage_dir}/.hfd/wget_urls.txt"

    if bash "$HFD" lgy0404/memgui-bench-trajs \
      --dataset \
      --local-dir "$stage_dir" \
      --include "$zip_name" \
      --tool aria2c \
      -x "$STAGE_HFD_THREADS" \
      -j "$STAGE_HFD_JOBS"; then
      if zip_is_complete_at "$staged_zip" "$expected_size"; then
        echo "[$(date -Is)] staged ${zip_name} complete"
        scripts/import_staged_traj_zips.sh "$agent_name"
        return 0
      fi
      echo "[$(date -Is)] staged ${zip_name} did not pass size/completion check; retrying" >&2
    else
      echo "[$(date -Is)] staged download attempt failed for ${zip_name}; retrying" >&2
    fi

    if [[ -f "$promoted_marker" ]]; then
      echo "ok ${agent_name}: staged partial promoted to root after interrupted attempt"
      return 0
    fi

    sleep 10
  done

  echo "[$(date -Is)] staged download failed for ${zip_name}" >&2
  return 1
}

echo "[$(date -Is)] starting staged trajectory downloads"
echo "targets: ${TARGET_AGENTS[*]}"
echo "max_parallel=${MAX_PARALLEL_STAGE_DOWNLOADS} threads_per_file=${STAGE_HFD_THREADS}"

failed=0
running=0

for agent_name in "${TARGET_AGENTS[@]}"; do
  log_path="traj_logs/_parallel_logs/${agent_name}.log"
  download_agent "$agent_name" >> "$log_path" 2>&1 &
  echo "started ${agent_name}: log ${log_path}"
  running=$((running + 1))

  if [[ "$running" -ge "$MAX_PARALLEL_STAGE_DOWNLOADS" ]]; then
    if ! wait -n; then
      failed=1
    fi
    running=$((running - 1))
  fi
done

while [[ "$running" -gt 0 ]]; do
  if ! wait -n; then
    failed=1
  fi
  running=$((running - 1))
done

scripts/import_staged_traj_zips.sh "${TARGET_AGENTS[@]}"

if [[ "$failed" == 0 ]]; then
  echo "[$(date -Is)] staged trajectory downloads finished"
else
  echo "[$(date -Is)] staged trajectory downloads finished with failures" >&2
fi

exit "$failed"
