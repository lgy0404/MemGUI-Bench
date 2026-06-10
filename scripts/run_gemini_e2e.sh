#!/usr/bin/env bash
set -euo pipefail

sudo uv run mg env run --count 4 --launch-interval 20

sudo env HISTORY_N_IMAGES=3 uv run mg eval \
    --agent_type general_e2e \
    --task ALL \
    --max_round 50 \
    --step_wait_time 3 \
    --model_name gemini-3-pro-preview \
    --log_file_root traj_logs/memgui_gemini_e2e \
    --max_concurrency 4
