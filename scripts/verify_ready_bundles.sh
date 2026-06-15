#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

shopt -s nullglob
bundles=(docs/trajs/*.json.gz)

if [[ "${#bundles[@]}" -eq 0 ]]; then
  echo "No trajectory bundles found under docs/trajs"
  exit 0
fi

for bundle in "${bundles[@]}"; do
  agent_file="${bundle##*/}"
  agent_name="${agent_file%.json.gz}"
  video="docs/trajs/${agent_name}.mp4"
  if [[ ! -f "$video" ]]; then
    echo "skip ${agent_name}: missing ${video}"
    continue
  fi
  python3 scripts/verify_traj_bundles.py "$bundle"
done

python3 scripts/verify_traj_site.py
