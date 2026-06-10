#!/usr/bin/env bash
set -e

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

uv sync
echo "MemGUI-Bench is ready. Try: uv run mg env check"
