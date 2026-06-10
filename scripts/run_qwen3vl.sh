#!/usr/bin/env bash
set -euo pipefail

sudo uv run mg env run --count 4 --launch-interval 20

sudo uv run mg eval \
    --agent_type qwen3vl \
    --task ALL \
    --max_round 50 \
    --model_name qwen3-vl-8b \
    --step_wait_time 3 \
    --log_file_root traj_logs/memgui_qwen3vl \
    --max_concurrency 4
