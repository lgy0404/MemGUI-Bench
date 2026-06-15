#!/usr/bin/env python3
"""Smoke-test legacy MemGUI zip auto-detection and bundling."""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_frame(path: Path, color: tuple[int, int, int], label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1080, 2400), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 120, 1000, 360), outline=(255, 255, 255), width=8)
    draw.text((120, 190), label, fill=(255, 255, 255))
    image.save(path)


def _make_legacy_attempt(root: Path, task: str, agent: str, score: int, screenshot_style: str = "raw") -> None:
    attempt = root / "_memgui_eval" / task / agent / "attempt_1"
    log = [
        {
            "step": 1,
            "prediction": f"<think>Inspect {task}</think>Tap the primary target.",
            "action": ["click", {"detail_type": "coordinates", "detail": [320, 760]}],
        },
        {
            "step": 2,
            "prediction": "Swipe to confirm.",
            "action": ["drag", {"detail_type": "coordinates", "detail": [500, 1600, 500, 900]}],
        },
    ]
    _write_json(attempt / "log.json", log)
    _write_json(attempt / "final_decision.json", {"decision": score, "reason": f"{task} scored {score}"})
    if screenshot_style == "single_actions":
        _write_frame(attempt / "single_actions" / "step_1.png", (32, 84, 147), f"{task} step 1")
        _write_frame(attempt / "single_actions" / "step_2.png", (9, 120, 107), f"{task} step 2")
    else:
        _write_frame(attempt / "0.png", (32, 84, 147), f"{task} frame 0")
        _write_frame(attempt / "1.png", (9, 120, 107), f"{task} frame 1")


def _make_legacy_zip(tmpdir: Path) -> Path:
    source = tmpdir / "legacy_source"
    agent = "smoke-agent"
    _make_legacy_attempt(source, "smoke_task_pass", agent, 1)
    _make_legacy_attempt(source, "smoke_task_fail", agent, 0)
    _make_legacy_attempt(source, "smoke_task_single_actions", agent, 1, screenshot_style="single_actions")
    results = (
        "task_identifier,task_description\n"
        "smoke_task_pass,Open the app and complete the pass task\n"
        "smoke_task_fail,Open the app and complete the fail task\n"
        "smoke_task_single_actions,Open the app and complete the fallback screenshot task\n"
    )
    (source / "_memgui_eval" / "results.csv").write_text(results, encoding="utf-8")

    zip_path = tmpdir / "legacy_source.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source))
    return zip_path


def _load_bundle(path: Path) -> dict[str, object]:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise TypeError("bundle root is not an object")
    return data


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="memgui_legacy_smoke_") as temp_name:
        tmpdir = Path(temp_name)
        zip_path = _make_legacy_zip(tmpdir)
        output_dir = tmpdir / "trajs"
        output = output_dir / "smoke-agent.json.gz"
        converted_root = tmpdir / "converted"

        bundle_result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "docs" / "bundle_trajs.py"),
                str(zip_path),
                "--with-screenshots",
                "-o",
                str(output),
                "--converted-root",
                str(converted_root),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if bundle_result.returncode != 0:
            print(bundle_result.stdout, end="")
            print(bundle_result.stderr, end="", file=sys.stderr)
            return bundle_result.returncode

        verify_result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_traj_bundles.py"), str(output)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        print(bundle_result.stdout, end="")
        print(verify_result.stdout, end="")
        if verify_result.returncode != 0:
            print(verify_result.stderr, end="", file=sys.stderr)
            return verify_result.returncode

        data = _load_bundle(output)
        tasks = [key for key in data if key != "_meta"]
        meta = data.get("_meta")
        converted = converted_root / zip_path.stem
        checks = [
            (converted.exists(), "converted legacy directory exists"),
            ((converted / "metadata.json").exists(), "converted metadata exists"),
            (len(tasks) == 3, "three legacy tasks bundled"),
            (isinstance(meta, dict) and meta.get("video_file") == "smoke-agent.mp4", "local MP4 metadata exists"),
            ((output_dir / "smoke-agent.mp4").exists(), "local MP4 file exists"),
            ((output_dir / "index.json").exists(), "manifest written next to output"),
        ]
        ok = True
        for passed, label in checks:
            print(f"{'OK' if passed else 'MISS'}  {label}")
            ok &= passed

        for task_name in tasks:
            task = data.get(task_name)
            traj = task.get("traj") if isinstance(task, dict) else None
            if not isinstance(traj, list) or len(traj) != 2:
                print(f"MISS  {task_name}: expected two trajectory steps")
                ok = False
                continue
            has_goal = all(bool(step.get("task_goal")) for step in traj if isinstance(step, dict))
            has_frames = all(isinstance(step.get("frame_index"), int) for step in traj if isinstance(step, dict))
            print(f"{'OK' if has_goal else 'MISS'}  {task_name}: task goals filled from legacy catalog")
            print(f"{'OK' if has_frames else 'MISS'}  {task_name}: screenshot frame indexes assigned")
            ok &= has_goal and has_frames

        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
