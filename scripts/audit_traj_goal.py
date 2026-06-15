#!/usr/bin/env python3
"""Audit MemGUI trajectory download, extraction, and docs bundle completion."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = [
    "agent-s2",
    "gui-owl-7b",
    "m3a",
    "mobile-agent-e",
    "qwen3-vl-8b-instruct",
    "t3a",
]
EXPECTED_BYTES = {
    "agent-s2": 21203200605,
    "gui-owl-7b": 32089648797,
    "m3a": 21295322173,
    "mobile-agent-e": 25785494378,
    "qwen3-vl-8b-instruct": 43499068026,
    "t3a": 22437818031,
}


def check(condition: bool, label: str) -> bool:
    print(f"{'OK' if condition else 'MISS'}  {label}")
    return condition


def extraction_matches_zip(marker: Path, zip_path: Path) -> bool:
    if not marker.exists() or not zip_path.exists():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return False
    stat = zip_path.stat()
    try:
        source = Path(str(data.get("source", ""))).resolve()
    except Exception:
        return False
    return (
        source == zip_path.resolve()
        and data.get("source_size") == stat.st_size
        and data.get("source_mtime_ns") == stat.st_mtime_ns
    )


def main() -> int:
    ok = True
    all_bundle_files_exist = True
    manifest_path = ROOT / "docs" / "trajs" / "index.json"
    manifest_files: set[str] = set()
    if manifest_path.exists():
        try:
            manifest_files = set(json.loads(manifest_path.read_text(encoding="utf-8")).get("files", []))
        except Exception:
            pass

    for agent in AGENTS:
        zip_path = ROOT / "traj_logs" / f"{agent}.zip"
        aria_path = zip_path.with_suffix(".zip.aria2")
        extract_marker = ROOT / "traj_logs" / agent / ".extract_complete"
        bundle_path = ROOT / "docs" / "trajs" / f"{agent}.json.gz"
        video_path = ROOT / "docs" / "trajs" / f"{agent}.mp4"
        manifest_entry = f"trajs/{agent}.json.gz"
        agent_data_path = ROOT / "docs" / "data" / "agents" / f"{agent}.json"
        expected_bytes = EXPECTED_BYTES[agent]
        agent_traj_file = None
        if agent_data_path.exists():
            try:
                agent_traj_file = json.loads(agent_data_path.read_text(encoding="utf-8")).get("trajFile")
            except Exception:
                agent_traj_file = None

        zip_complete = (
            zip_path.exists()
            and not aria_path.exists()
            and zip_path.stat().st_size == expected_bytes
        )
        ok &= check(zip_complete, f"{agent}: zip fully downloaded ({expected_bytes} bytes)")
        ok &= check(extraction_matches_zip(extract_marker, zip_path), f"{agent}: zip extracted from current zip")
        ok &= check(bundle_path.exists(), f"{agent}: json.gz bundle exists")
        ok &= check(video_path.exists(), f"{agent}: mp4 frame store exists")
        ok &= check(manifest_entry in manifest_files, f"{agent}: manifest entry exists")
        ok &= check(agent_traj_file == manifest_entry, f"{agent}: agent JSON trajFile points to bundle")
        all_bundle_files_exist &= bundle_path.exists() and video_path.exists()

    if all_bundle_files_exist:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_traj_bundles.py")],
            cwd=ROOT,
        )
        ok &= check(result.returncode == 0, "all generated bundles pass content validation")
    else:
        ok &= check(False, "all generated bundles pass content validation")

    site_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_traj_site.py")],
        cwd=ROOT,
    )
    ok &= check(site_result.returncode == 0, "MemGUI docs trajectory viewer and Arena integration pass validation")

    legacy_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_legacy_conversion_smoke.py")],
        cwd=ROOT,
    )
    ok &= check(legacy_result.returncode == 0, "legacy MemGUI zip auto-detection and conversion smoke test passes")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
