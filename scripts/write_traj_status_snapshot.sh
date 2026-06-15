#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOG_FILE="${TRAJ_STATUS_HISTORY_LOG:-traj_logs/status_history.log}"
mkdir -p "$(dirname "$LOG_FILE")"

{
  echo "[$(date -Is)] trajectory status snapshot"
  scripts/check_traj_status.sh
  echo
} >> "$LOG_FILE"

echo "Wrote trajectory status snapshot to ${LOG_FILE}"
