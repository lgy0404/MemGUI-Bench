#!/usr/bin/env python3
"""Verify generated MemGUI trajectory bundles and their MP4 frame stores."""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAJ_DIR = ROOT / "docs" / "trajs"
EXPECTED_TASKS = 128


def _positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and value > 0


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and value > 0


def _task_score(result: object) -> float | None:
    if not isinstance(result, str):
        return None
    for line in result.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() == "score":
            try:
                return float(value.strip())
            except ValueError:
                return None
    return None


def _read_manifest() -> set[str] | None:
    manifest_path = TRAJ_DIR / "index.json"
    if not manifest_path.exists():
        print(f"Missing manifest: {manifest_path}", file=sys.stderr)
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"Failed to parse {manifest_path}: {error}", file=sys.stderr)
        return None
    files = data.get("files")
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        print(f"{manifest_path}: expected a string array at files", file=sys.stderr)
        return None
    return set(files)


def _probe_video(path: Path) -> dict[str, int | None]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,nb_frames",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise ValueError("no video stream found")
    stream = streams[0]
    nb_frames = stream.get("nb_frames")
    return {
        "width": int(stream["width"]) if str(stream.get("width", "")).isdigit() else None,
        "height": int(stream["height"]) if str(stream.get("height", "")).isdigit() else None,
        "nb_frames": int(nb_frames) if str(nb_frames or "").isdigit() else None,
    }


def _local_video_path(bundle_path: Path, video_name: str) -> Path | None:
    if video_name.startswith(("http://", "https://")):
        return None
    candidate = Path(video_name)
    if candidate.is_absolute():
        return None
    resolved = (bundle_path.parent / candidate).resolve()
    try:
        resolved.relative_to(bundle_path.parent.resolve())
    except ValueError:
        return None
    return resolved


def verify_bundle(path: Path, manifest_files: set[str] | None = None) -> bool:
    ok = True
    try:
        with gzip.open(path, "rb") as file:
            data = json.load(file)
    except Exception as error:
        print(f"{path.name}: failed to read gzip JSON: {error}", file=sys.stderr)
        return False

    if not isinstance(data, dict):
        print(f"{path.name}: root JSON must be an object", file=sys.stderr)
        return False

    tasks = [key for key in data if key != "_meta"]
    meta = data.get("_meta") or {}
    video_name = meta.get("video_file")
    video_path = _local_video_path(path, video_name) if isinstance(video_name, str) else None
    frame_indices: list[int] = []
    step_count = 0
    unscored_tasks = 0

    if not tasks:
        print(f"{path.name}: no tasks", file=sys.stderr)
        ok = False
    elif len(tasks) != EXPECTED_TASKS:
        print(f"{path.name}: warning: expected {EXPECTED_TASKS} tasks, found {len(tasks)}", file=sys.stderr)
    if not isinstance(meta, dict):
        print(f"{path.name}: _meta must be an object", file=sys.stderr)
        ok = False
        meta = {}
    if manifest_files is not None and f"trajs/{path.name}" not in manifest_files:
        print(f"{path.name}: missing from trajs/index.json", file=sys.stderr)
        ok = False

    for field in ("total_frames", "original_width", "original_height", "display_width", "display_height"):
        if not _positive_int(meta.get(field)):
            print(f"{path.name}: missing or invalid _meta.{field}", file=sys.stderr)
            ok = False
    if not _positive_number(meta.get("fps")):
        print(f"{path.name}: missing or invalid _meta.fps", file=sys.stderr)
        ok = False

    for task_name in sorted(tasks):
        task = data.get(task_name)
        if not isinstance(task, dict):
            print(f"{path.name}: task {task_name} is not an object", file=sys.stderr)
            ok = False
            continue
        traj = task.get("traj")
        if not isinstance(traj, list) or not traj:
            print(f"{path.name}: task {task_name} has no steps", file=sys.stderr)
            ok = False
            continue
        score = _task_score(task.get("result"))
        if score not in {0.0, 1.0}:
            unscored_tasks += 1
        step_count += len(traj)
        for index, step in enumerate(traj):
            if not isinstance(step, dict):
                print(f"{path.name}: task {task_name} step {index} is not an object", file=sys.stderr)
                ok = False
                continue
            frame_index = step.get("frame_index")
            if frame_index is None:
                continue
            if not isinstance(frame_index, int) or frame_index < 0:
                print(f"{path.name}: task {task_name} step {index} has invalid frame_index", file=sys.stderr)
                ok = False
            else:
                frame_indices.append(frame_index)

    total_frames = meta.get("total_frames") if isinstance(meta.get("total_frames"), int) else None
    if total_frames is not None:
        unique_frames = sorted(set(frame_indices))
        expected_frames = list(range(total_frames))
        if unique_frames != expected_frames:
            print(
                f"{path.name}: frame_index values do not cover 0..{total_frames - 1} exactly",
                file=sys.stderr,
            )
            ok = False

    if not video_name:
        print(f"{path.name}: missing _meta.video_file", file=sys.stderr)
        ok = False
    elif not isinstance(video_name, str):
        print(f"{path.name}: _meta.video_file must be a string", file=sys.stderr)
        ok = False
    elif video_name.startswith(("http://", "https://")):
        print(f"{path.name}: _meta.video_file should be a local MP4 path for this repo", file=sys.stderr)
        ok = False
    elif video_path is None:
        print(f"{path.name}: _meta.video_file must stay inside {path.parent}", file=sys.stderr)
        ok = False
    elif not video_path.exists():
        print(f"{path.name}: missing video {video_name}", file=sys.stderr)
        ok = False
    else:
        try:
            video = _probe_video(video_path)
            if video["width"] != meta.get("display_width"):
                print(f"{path.name}: MP4 width {video['width']} != _meta.display_width", file=sys.stderr)
                ok = False
            if video["height"] != meta.get("display_height"):
                print(f"{path.name}: MP4 height {video['height']} != _meta.display_height", file=sys.stderr)
                ok = False
            if video["nb_frames"] is not None and video["nb_frames"] != meta.get("total_frames"):
                print(f"{path.name}: MP4 frames {video['nb_frames']} != _meta.total_frames", file=sys.stderr)
                ok = False
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as error:
            print(f"{path.name}: ffprobe failed for {video_name}: {error}", file=sys.stderr)
            ok = False

    score_note = f", {unscored_tasks} unscored" if unscored_tasks else ""
    print(
        f"{path.name}: {len(tasks)} tasks, {step_count} steps, "
        f"{total_frames or 0} frames{score_note}, video={video_name or '-'}"
    )
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "bundles",
        nargs="*",
        help="Optional bundle paths. Defaults to docs/trajs/*.json.gz with manifest checks.",
    )
    args = parser.parse_args()

    bundles = [Path(item) for item in args.bundles] if args.bundles else sorted(TRAJ_DIR.glob("*.json.gz"))
    if not bundles:
        print(f"No bundles found under {TRAJ_DIR}", file=sys.stderr)
        return 1

    manifest_files = None
    ok = True
    if not args.bundles:
        manifest_files = _read_manifest()
        if manifest_files is None:
            ok = False
        else:
            bundle_entries = {f"trajs/{path.name}" for path in bundles}
            stale_entries = manifest_files - bundle_entries
            missing_entries = bundle_entries - manifest_files
            for entry in sorted(stale_entries):
                print(f"manifest: stale entry {entry}", file=sys.stderr)
                ok = False
            for entry in sorted(missing_entries):
                print(f"manifest: missing entry {entry}", file=sys.stderr)
                ok = False

    for path in bundles:
        ok &= verify_bundle(path, manifest_files=manifest_files)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
