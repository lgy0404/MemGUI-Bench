#!/usr/bin/env bash
set -euo pipefail

sudo uv run mg env run --count 4 --launch-interval 20

sudo uv run mg eval \
    --agent-type planner_executor \
    --task ALL \
    --max-round 50 \
    --step-wait-time 3 \
    --model-name "${PLANNER_MODEL_NAME:-qwen3-vl-8b}" \
    --executor-agent-class uiins \
    --executor-model-name "${EXECUTOR_MODEL_NAME:-qwen3-vl-8b}" \
    --log-file-root traj_logs/memgui-agentic \
    --max-concurrency 4
