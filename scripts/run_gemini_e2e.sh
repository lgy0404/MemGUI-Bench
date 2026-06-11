#!/usr/bin/env bash
set -euo pipefail

sudo uv run mg env run --count 4 --launch-interval 20

sudo env HISTORY_N_IMAGES=3 uv run mg eval \
    --agent-type general_e2e \
    --task ALL \
    --max-round 50 \
    --step-wait-time 3 \
    --model-name gemini-3-pro-preview \
    --log-file-root traj_logs/memgui-gemini-e2e \
    --max-concurrency 4
