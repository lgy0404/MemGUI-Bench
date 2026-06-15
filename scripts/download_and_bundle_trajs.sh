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

mkdir -p traj_logs docs/trajs traj_logs/_parallel_downloads traj_logs/_parallel_logs

DOWNLOAD_CONCURRENCY="${DOWNLOAD_CONCURRENCY:-3}"
HFD_THREADS="${HFD_THREADS:-6}"
HFD_JOBS="${HFD_JOBS:-1}"
MAX_DOWNLOAD_ATTEMPTS="${MAX_DOWNLOAD_ATTEMPTS:-50}"
DOWNLOAD_RETRY_DELAY_SECONDS="${DOWNLOAD_RETRY_DELAY_SECONDS:-10}"

if ! [[ "$DOWNLOAD_CONCURRENCY" =~ ^[0-9]+$ ]] || [[ "$DOWNLOAD_CONCURRENCY" -lt 1 ]]; then
  echo "DOWNLOAD_CONCURRENCY must be a positive integer" >&2
  exit 2
fi

AGENT_ZIPS=(
  agent-s2.zip
  gui-owl-7b.zip
  m3a.zip
  mobile-agent-e.zip
  qwen3-vl-8b-instruct.zip
  t3a.zip
)

declare -A EXPECTED_BYTES=(
  [agent-s2]=21203200605
  [gui-owl-7b]=32089648797
  [m3a]=21295322173
  [mobile-agent-e]=25785494378
  [qwen3-vl-8b-instruct]=43499068026
  [t3a]=22437818031
)

zip_is_complete_at() {
  local zip_path="$1"
  local expected_size="$2"

  [[ -f "$zip_path" ]] || return 1
  [[ ! -f "${zip_path}.aria2" ]] || return 1
  [[ "$(stat -c '%s' "$zip_path")" == "$expected_size" ]]
}

zip_is_complete() {
  local agent_name="$1"
  zip_is_complete_at "traj_logs/${agent_name}.zip" "${EXPECTED_BYTES[$agent_name]}"
}

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

verify_bundle() {
  local agent_name="$1"
  local bundle_path="docs/trajs/${agent_name}.json.gz"
  local video_path="docs/trajs/${agent_name}.mp4"

  [[ -f "$bundle_path" && -f "$video_path" ]] || return 1
  if [[ -f scripts/verify_traj_bundles.py ]]; then
    python3 scripts/verify_traj_bundles.py "$bundle_path"
  fi
}

stage_dir_for() {
  local agent_name="$1"
  printf 'traj_logs/_parallel_downloads/%s\n' "$agent_name"
}

seed_stage_from_root_if_better() {
  local agent_name="$1"
  local zip_name="${agent_name}.zip"
  local root_zip="traj_logs/${zip_name}"
  local root_aria="${root_zip}.aria2"
  local stage_dir
  local staged_zip
  local staged_aria
  local root_downloaded
  local staged_downloaded
  local backup_dir
  local stamp

  stage_dir="$(stage_dir_for "$agent_name")"
  staged_zip="${stage_dir}/${zip_name}"
  staged_aria="${staged_zip}.aria2"
  mkdir -p "$stage_dir"

  [[ -f "$root_zip" ]] || return 0
  zip_is_complete "$agent_name" && return 0
  zip_is_complete_at "$staged_zip" "${EXPECTED_BYTES[$agent_name]}" && return 0

  root_downloaded="$(downloaded_bytes "$root_zip")"
  staged_downloaded="$(downloaded_bytes "$staged_zip")"
  if [[ "$root_downloaded" -le "$staged_downloaded" ]]; then
    echo "[$(date -Is)] ${zip_name}: staged partial is at least as large; keeping staged copy"
    return 0
  fi

  stamp="$(date +%Y%m%d_%H%M%S)"
  backup_dir="traj_logs/_parallel_replaced_partials_${stamp}"
  mkdir -p "$backup_dir"

  if [[ -f "$staged_zip" ]]; then
    mv "$staged_zip" "${backup_dir}/${zip_name}"
  fi
  if [[ -f "$staged_aria" ]]; then
    mv "$staged_aria" "${backup_dir}/${zip_name}.aria2"
  fi

  mv "$root_zip" "$staged_zip"
  if [[ -f "$root_aria" ]]; then
    mv "$root_aria" "$staged_aria"
  fi

  echo "[$(date -Is)] ${zip_name}: moved larger root partial (${root_downloaded} bytes) into ${stage_dir}"
}

import_staged_zip() {
  local agent_name="$1"

  if [[ -x scripts/import_staged_traj_zips.sh ]]; then
    scripts/import_staged_traj_zips.sh "$agent_name"
  fi
}

download_agent() {
  local agent_name="$1"
  local zip_name="${agent_name}.zip"
  local stage_dir
  local staged_zip
  local attempt

  stage_dir="$(stage_dir_for "$agent_name")"
  staged_zip="${stage_dir}/${zip_name}"

  import_staged_zip "$agent_name"
  if zip_is_complete "$agent_name"; then
    echo "[$(date -Is)] ${zip_name} already complete in traj_logs"
    return 0
  fi

  seed_stage_from_root_if_better "$agent_name"
  if zip_is_complete_at "$staged_zip" "${EXPECTED_BYTES[$agent_name]}"; then
    import_staged_zip "$agent_name"
    return 0
  fi

  for ((attempt = 1; attempt <= MAX_DOWNLOAD_ATTEMPTS; attempt++)); do
    import_staged_zip "$agent_name"
    if zip_is_complete "$agent_name"; then
      echo "[$(date -Is)] ${zip_name} complete in traj_logs"
      return 0
    fi
    if zip_is_complete_at "$staged_zip" "${EXPECTED_BYTES[$agent_name]}"; then
      import_staged_zip "$agent_name"
      return 0
    fi

    echo "[$(date -Is)] Downloading ${zip_name} in ${stage_dir} (attempt ${attempt}/${MAX_DOWNLOAD_ATTEMPTS})"

    # hfd/aria2 can save signed CDN URLs back into these files after a 403.
    # Regenerate them each attempt so resumed downloads get fresh mirror URLs.
    rm -f "${stage_dir}/.hfd/aria2c_urls.txt" "${stage_dir}/.hfd/wget_urls.txt"

    if bash "$HFD" lgy0404/memgui-bench-trajs \
      --dataset \
      --local-dir "$stage_dir" \
      --include "$zip_name" \
      --tool aria2c \
      -x "$HFD_THREADS" \
      -j "$HFD_JOBS"; then
      if zip_is_complete_at "$staged_zip" "${EXPECTED_BYTES[$agent_name]}"; then
        echo "[$(date -Is)] staged ${zip_name} complete"
        import_staged_zip "$agent_name"
        return 0
      fi
      echo "[$(date -Is)] ${zip_name} did not pass size/completion check; retrying" >&2
    else
      echo "[$(date -Is)] Download attempt failed for ${zip_name}; retrying" >&2
    fi

    sleep "$DOWNLOAD_RETRY_DELAY_SECONDS"
  done

  echo "[$(date -Is)] Download failed for ${zip_name} after ${MAX_DOWNLOAD_ATTEMPTS} attempts" >&2
  return 1
}

run_parallel_downloads() {
  local zip_name
  local agent_name
  local log_path
  local running=0
  local failed=0

  echo "[$(date -Is)] Starting parallel trajectory downloads"
  echo "[$(date -Is)] concurrency=${DOWNLOAD_CONCURRENCY} threads_per_file=${HFD_THREADS} jobs_per_hfd=${HFD_JOBS}"

  for zip_name in "${AGENT_ZIPS[@]}"; do
    agent_name="${zip_name%.zip}"
    log_path="traj_logs/_parallel_logs/${agent_name}.download.log"
    echo "[$(date -Is)] starting ${agent_name}; log: ${log_path}"
    download_agent "$agent_name" >> "$log_path" 2>&1 &
    running=$((running + 1))

    if [[ "$running" -ge "$DOWNLOAD_CONCURRENCY" ]]; then
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

  if [[ -x scripts/import_staged_traj_zips.sh ]]; then
    scripts/import_staged_traj_zips.sh
  fi

  return "$failed"
}

if ! run_parallel_downloads; then
  echo "[$(date -Is)] One or more parallel downloads failed; finalizing any completed zips" >&2
  scripts/finalize_ready_trajs.sh
  exit 1
fi

echo "[$(date -Is)] All downloads complete; bundling ready trajectories"
scripts/finalize_ready_trajs.sh

bundle_failed=0
for zip_name in "${AGENT_ZIPS[@]}"; do
  agent_name="${zip_name%.zip}"
  if verify_bundle "$agent_name"; then
    echo "[$(date -Is)] ${agent_name} bundle verified"
  else
    echo "[$(date -Is)] ${agent_name} bundle verification failed" >&2
    bundle_failed=1
  fi
done

if [[ "$bundle_failed" != 0 ]]; then
  exit 1
fi

if [[ -f scripts/verify_traj_site.py ]]; then
  python3 scripts/verify_traj_site.py
fi

echo "[$(date -Is)] Done"
