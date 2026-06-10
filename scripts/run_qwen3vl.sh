#!/usr/bin/env bash
set -euo pipefail

sudo uv run mg env run --count 4 --launch-interval 20

sudo uv run mg eval \
    --agent-type qwen3vl \
    --task ALL \
    --max-round 50 \
    --model-name qwen3-vl-8b \
    --step-wait-time 3 \
    --log-file-root traj_logs/memgui-qwen3vl \
    --max-concurrency 4
