#!/usr/bin/env python3
"""Verify the static docs trajectory viewer and Arena integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TRAJ_AGENTS = [
    "agent-s2",
    "gui-owl-7b",
    "m3a",
    "mobile-agent-e",
    "qwen3-vl-8b-instruct",
    "t3a",
]


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def check(condition: bool, label: str) -> bool:
    print(f"{'OK' if condition else 'MISS'}  {label}")
    return condition


def main() -> int:
    ok = True

    index_html = read(DOCS / "index.html")
    arena_html = read(DOCS / "arena.html")
    config_js = read(DOCS / "js" / "config.js")
    leaderboard_js = read(DOCS / "js" / "leaderboard.js")
    viewer_js = read(DOCS / "js" / "traj-viewer.js")
    arena_js = read(DOCS / "js" / "arena.js")

    ok &= check("css/traj.css" in index_html, "homepage loads trajectory CSS")
    ok &= check("js/traj-viewer.js" in index_html, "homepage loads trajectory viewer JS")
    ok &= check('href="arena.html"' in index_html, "homepage links to Arena")
    ok &= check("css/arena.css" in arena_html, "Arena loads Arena CSS")
    ok &= check("js/arena.js" in arena_html, "Arena loads Arena JS")
    ok &= check("js/traj-viewer.js" in arena_html, "Arena loads shared trajectory viewer")
    ok &= check("TRAJ_MANIFEST_PATHS" in config_js, "config defines trajectory manifest paths")
    ok &= check("loadTrajManifest" in config_js, "config exposes trajectory manifest loader")
    ok &= check("hasTrajectoryBundle" in config_js, "config exposes trajectory availability helper")
    ok &= check("await loadTrajManifest()" in leaderboard_js, "leaderboard waits for trajectory manifest")
    ok &= check("data-traj-file" in leaderboard_js, "leaderboard renders trajectory trigger")
    ok &= check("arena.html?model=" in leaderboard_js, "leaderboard links agents to Arena")
    ok &= check("window.MemGUITraj" in viewer_js, "viewer exposes shared MemGUITraj API")
    ok &= check("DecompressionStream" in viewer_js, "viewer can read gzip JSON in browser")
    ok &= check("frame_index" in viewer_js, "viewer renders screenshot frames by frame_index")
    ok &= check("MemGUITraj.getTrajectoryData" in arena_js, "Arena loads trajectory bundles")
    ok &= check("hasTrajectoryBundle" in arena_js, "Arena filters to bundled agents")

    for rel_path in (
        "css/traj.css",
        "css/arena.css",
        "js/traj-viewer.js",
        "js/arena.js",
        "trajs/index.json",
    ):
        path = DOCS / rel_path
        ok &= check(path.exists() and path.stat().st_size > 0, f"{rel_path} exists and is non-empty")

    for agent in TRAJ_AGENTS:
        agent_path = DOCS / "data" / "agents" / f"{agent}.json"
        try:
            data = json.loads(agent_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        ok &= check(data.get("trajFile") == f"trajs/{agent}.json.gz", f"{agent}: trajFile points to docs/trajs bundle")

    try:
        manifest = json.loads((DOCS / "trajs" / "index.json").read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    files = manifest.get("files", [])
    ok &= check(isinstance(files, list), "trajectory manifest has a files list")
    for bundle_path in sorted((DOCS / "trajs").glob("*.json.gz")):
        entry = f"trajs/{bundle_path.name}"
        ok &= check(entry in files, f"{entry}: manifest entry exists")
        ok &= check(bundle_path.with_suffix("").with_suffix(".mp4").exists(), f"{entry}: mp4 exists beside bundle")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
