#!/usr/bin/env bash
set -euo pipefail

sudo uv run mg env run --count 4 --launch-interval 20

sudo uv run mg eval \
    --agent_type planner_executor \
    --task ALL \
    --max_round 50 \
    --step_wait_time 3 \
    --model_name "${PLANNER_MODEL_NAME:-qwen3-vl-8b}" \
    --executor_agent_class uiins \
    --executor_model_name "${EXECUTOR_MODEL_NAME:-qwen3-vl-8b}" \
    --log_file_root traj_logs/memgui_agentic \
    --max_concurrency 4
