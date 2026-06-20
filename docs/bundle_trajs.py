#!/usr/bin/env python3
"""Bundle MemGUI-Bench trajectories for the static docs viewer.

The input can be either:
- a MobileWorld-style run directory with task folders containing traj.json
- a legacy MemGUI-Eval directory with task/agent/attempt_N/log.json
- a .zip archive containing either layout

Legacy inputs are converted to a MobileWorld-style directory first, then bundled
into docs/trajs/<agent>.json.gz plus a local MP4 with screenshot frames.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCREENSHOT_RESIZE_WIDTH = 270
VIDEO_FPS = 2
VIDEO_CRF = 30
PROGRESS_EVERY = 10
FRAME_PROGRESS_EVERY = 250


@dataclass
class LegacyAttempt:
    task_name: str
    agent_name: str
    attempt_num: int
    attempt_dir: Path


@dataclass
class TaskAttemptDir:
    task_name: str
    label: str
    attempt_num: int | None
    path: Path


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _safe_json_load(path: Path) -> Any:
    try:
        return _load_json(path)
    except Exception:
        return None


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _progress(message: str) -> None:
    print(f"[bundle_trajs] {message}", flush=True)


def _hardlink_or_copy(src: Path, dst: Path) -> None:
    _ensure_dir(dst.parent)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def _legacy_action_to_mobileworld(action: Any) -> dict[str, Any]:
    if isinstance(action, dict):
        return action
    if not isinstance(action, list) or not action:
        return {"action_type": "unknown"}

    action_type = action[0]
    detail = action[1] if len(action) > 1 and isinstance(action[1], dict) else {}
    detail_type = detail.get("detail_type")
    value = detail.get("detail")

    if detail_type == "coordinates" and isinstance(value, list):
        if action_type in {"click", "double_tap", "long_press"} and len(value) >= 2:
            return {"action_type": action_type, "x": value[0], "y": value[1]}
        if action_type in {"drag", "swipe"} and len(value) >= 4:
            return {
                "action_type": "drag",
                "start_x": value[0],
                "start_y": value[1],
                "end_x": value[2],
                "end_y": value[3],
            }
    if detail_type == "text":
        mapped = "input_text" if action_type in {"type", "input_text"} else action_type
        return {"action_type": mapped, "text": value or ""}
    if detail_type == "direction":
        mapped = "scroll" if action_type in {"scroll", "swipe"} else action_type
        return {"action_type": mapped, "direction": value or ""}
    if detail_type == "app":
        return {"action_type": "open_app", "app_name": value or ""}
    if detail_type == "status" and isinstance(value, str):
        return {"action_type": value}
    return {"action_type": str(action_type), "raw_action": action}


def _score_from_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return 1.0 if float(value) > 0 else 0.0

    normalized = str(value).strip().lower()
    if normalized in {"1", "1.0", "true", "yes", "y", "pass", "passed", "success", "succeeded", "correct"}:
        return 1.0
    if normalized in {"0", "0.0", "false", "no", "n", "fail", "failed", "failure", "incorrect"}:
        return 0.0
    return None


def _load_legacy_task_catalog(source_dir: Path) -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    for csv_path in source_dir.rglob("results.csv"):
        try:
            with csv_path.open(newline="", encoding="utf-8") as file:
                for row in csv.DictReader(file):
                    task_id = (row.get("task_identifier") or row.get("task_id") or row.get("task") or "").strip()
                    if task_id:
                        catalog.setdefault(task_id, row)
        except Exception as error:
            print(f"Warning: failed to read legacy task catalog {csv_path}: {error}", file=sys.stderr)
    return catalog


def _task_goal_from_catalog(task_name: str, task_catalog: dict[str, dict[str, str]] | None) -> str:
    catalog_row = (task_catalog or {}).get(task_name) or {}
    for key in ("task_description", "description", "goal", "task_goal", "instruction"):
        if catalog_row.get(key):
            return str(catalog_row[key])
    return ""


def _infer_legacy_attempt(path: Path, root: Path) -> LegacyAttempt | None:
    if path.name != "log.json":
        return None
    attempt_dir = path.parent
    match = re.match(r"attempt_(\d+)$", attempt_dir.name)
    attempt_num = int(match.group(1)) if match else 1

    parts = attempt_dir.parts
    task_name = attempt_dir.parent.parent.name if len(attempt_dir.parents) >= 2 else root.name
    agent_name = attempt_dir.parent.name if attempt_dir.parent != root else "agent"

    if "_memgui_eval" in parts:
        idx = parts.index("_memgui_eval")
        if idx + 2 < len(parts):
            task_name = parts[idx + 1]
            agent_name = parts[idx + 2]
    elif match and attempt_dir.parent != root:
        agent_name = attempt_dir.parent.name
        if attempt_dir.parent.parent != root.parent:
            task_name = attempt_dir.parent.parent.name

    summary = _safe_json_load(attempt_dir / "evaluation_summary.json")
    if isinstance(summary, dict) and summary.get("task_identifier") and not re.match(r"^\d{3}-", task_name):
        task_name = str(summary["task_identifier"])

    return LegacyAttempt(task_name, agent_name, attempt_num, attempt_dir)


def discover_legacy_attempts(root: Path, attempt_num: int | None = None) -> list[LegacyAttempt]:
    attempts: list[LegacyAttempt] = []
    for log_path in root.rglob("log.json"):
        if any(part in {"single_actions", "visualize_actions", "puzzle"} for part in log_path.parts):
            continue
        attempt = _infer_legacy_attempt(log_path, root)
        if attempt and (attempt_num is None or attempt.attempt_num == attempt_num):
            attempts.append(attempt)

    attempts = sorted(attempts, key=lambda item: (item.task_name, item.attempt_num, str(item.attempt_dir)))
    if attempt_num is None:
        return attempts

    seen: set[str] = set()
    unique: list[LegacyAttempt] = []
    for attempt in attempts:
        if attempt.task_name in seen:
            continue
        seen.add(attempt.task_name)
        unique.append(attempt)
    return unique


def has_mobileworld_tasks(root: Path) -> bool:
    for traj_path in root.rglob("traj.json"):
        if "_memgui_eval" in traj_path.parts:
            continue
        data = _safe_json_load(traj_path)
        entry = data.get("0", data) if isinstance(data, dict) else None
        if isinstance(entry, dict) and isinstance(entry.get("traj"), list):
            return True
    return False


def _legacy_result_text(
    attempt_dir: Path,
    task_name: str,
    task_catalog: dict[str, dict[str, str]] | None = None,
) -> str | None:
    final = _safe_json_load(attempt_dir / "final_decision.json")
    summary = _safe_json_load(attempt_dir / "evaluation_summary.json")
    catalog_row = (task_catalog or {}).get(task_name) or {}

    decision = None
    reason = None
    if isinstance(final, dict):
        decision = final.get("decision", final.get("final_result"))
        reason = final.get("reason")
    if isinstance(summary, dict):
        decision = summary.get("final_result", decision)
        reason = summary.get("final_reason", reason)
    for key in (
        "score",
        "success",
        "passed",
        "pass",
        "final_result",
        "result",
        "decision",
        "is_success",
    ):
        if decision is None and catalog_row.get(key) not in {None, ""}:
            decision = catalog_row.get(key)
    reason = reason or catalog_row.get("reason") or catalog_row.get("final_reason")

    if decision is None and reason is None:
        return None
    score = _score_from_value(decision)
    if score is None:
        score = 0.0
    return f"score: {score:.1f}\nreason: {reason or 'No reason provided.'}"


def _legacy_task_goal(
    attempt_dir: Path,
    task_name: str,
    task_catalog: dict[str, dict[str, str]] | None = None,
) -> str:
    summary = _safe_json_load(attempt_dir / "evaluation_summary.json")
    if isinstance(summary, dict) and summary.get("task_description"):
        return str(summary["task_description"])
    return _task_goal_from_catalog(task_name, task_catalog)


def _legacy_screenshot_candidates(attempt_dir: Path, task_name: str, step_num: int) -> list[Path]:
    return [
        attempt_dir / f"{step_num - 1}.png",
        attempt_dir / f"{step_num}.png",
        attempt_dir / "screenshots" / f"{task_name}-0-{step_num}.png",
        attempt_dir / "screenshots" / f"{task_name}-0-{step_num - 1}.png",
        attempt_dir / "screenshots" / f"{step_num}.png",
        attempt_dir / "screenshots" / f"{step_num - 1}.png",
        attempt_dir / "single_actions" / f"step_{step_num}.png",
        attempt_dir / "visualize_actions" / f"step_{step_num}.png",
    ]


def convert_legacy_run(source_dir: Path, output_dir: Path, attempt_num: int | None = None) -> Path:
    attempts = discover_legacy_attempts(source_dir, attempt_num=attempt_num)
    if not attempts:
        attempt_desc = "legacy attempt log.json files" if attempt_num is None else f"legacy attempt_{attempt_num} log.json files"
        raise ValueError(f"No {attempt_desc} found under {source_dir}")
    task_catalog = _load_legacy_task_catalog(source_dir)
    if task_catalog:
        catalog_task_ids = set(task_catalog)
        before_count = len(attempts)
        attempts = [attempt for attempt in attempts if attempt.task_name in catalog_task_ids]
        skipped_count = before_count - len(attempts)
        if skipped_count:
            print(f"Skipped {skipped_count} legacy attempts not listed in results.csv")
        if not attempts:
            raise ValueError(f"No legacy attempts under {source_dir} matched results.csv task identifiers")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    _ensure_dir(output_dir)
    _progress(f"Converting {len(attempts)} legacy attempts -> {output_dir}")

    metadata = {
        "suite_family": "memgui_bench",
        "source_format": "legacy_memgui_eval",
        "source_dir": str(source_dir),
        "attempt_num": "all" if attempt_num is None else attempt_num,
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    for index, attempt in enumerate(attempts, start=1):
        if index == 1 or index % PROGRESS_EVERY == 0 or index == len(attempts):
            _progress(
                f"Converting attempt {index}/{len(attempts)}: "
                f"{attempt.task_name} attempt_{attempt.attempt_num}"
            )
        log_data = _load_json(attempt.attempt_dir / "log.json")
        if not isinstance(log_data, list):
            continue
        task_goal = _legacy_task_goal(attempt.attempt_dir, attempt.task_name, task_catalog)
        task_dir = output_dir / attempt.task_name / f"attempt_{attempt.attempt_num}"
        screenshots_dir = task_dir / "screenshots"
        _ensure_dir(screenshots_dir)

        steps = []
        for index, legacy_step in enumerate(log_data):
            if not isinstance(legacy_step, dict):
                continue
            step_num = int(legacy_step.get("step") or index + 1)
            action = legacy_step.get("mobileworld_action") or _legacy_action_to_mobileworld(
                legacy_step.get("action")
            )
            steps.append(
                {
                    "task_goal": task_goal,
                    "step": step_num,
                    "prediction": legacy_step.get("prediction") or legacy_step.get("thought") or "",
                    "action": action,
                    "ask_user_response": legacy_step.get("ask_user_response"),
                    "tool_call": legacy_step.get("tool_call"),
                }
            )

            src_image = next(
                (
                    candidate
                    for candidate in _legacy_screenshot_candidates(
                        attempt.attempt_dir,
                        attempt.task_name,
                        step_num,
                    )
                    if candidate.exists()
                ),
                None,
            )
            if src_image:
                dst_image = screenshots_dir / f"{attempt.task_name}-0-{step_num}.png"
                _hardlink_or_copy(src_image, dst_image)

        traj = {"0": {"traj": steps, "token_usage": {}}}
        (task_dir / "traj.json").write_text(
            json.dumps(traj, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result_text = _legacy_result_text(attempt.attempt_dir, attempt.task_name, task_catalog)
        if result_text:
            (task_dir / "result.txt").write_text(result_text, encoding="utf-8")

    task_count = len({attempt.task_name for attempt in attempts})
    _progress(f"Converted {len(attempts)} legacy attempts across {task_count} tasks -> {output_dir}")
    return output_dir


def _zip_marker_payload(input_path: Path) -> dict[str, Any]:
    stat = input_path.stat()
    return {
        "source": str(input_path.resolve()),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
    }


def _zip_marker_matches(marker: Path, input_path: Path) -> bool:
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return False
    return data == _zip_marker_payload(input_path)


def _safe_extract_zip(archive: zipfile.ZipFile, target: Path) -> None:
    target_root = target.resolve()
    for member in archive.infolist():
        destination = (target / member.filename).resolve()
        try:
            destination.relative_to(target_root)
        except ValueError as error:
            raise ValueError(f"Refusing unsafe zip member path: {member.filename}") from error
    archive.extractall(target)


def extract_zip_if_needed(input_path: Path, extract_root: Path | None = None) -> Path:
    if input_path.suffix.lower() != ".zip":
        return input_path
    target = (extract_root or input_path.parent) / input_path.stem
    marker = target / ".extract_complete"
    if marker.exists() and any(target.iterdir()) and _zip_marker_matches(marker, input_path):
        _progress(f"Using existing extraction: {target}")
        return target
    if target.exists():
        shutil.rmtree(target)
    _ensure_dir(target)
    _progress(f"Extracting {input_path} -> {target}")
    with zipfile.ZipFile(input_path) as archive:
        _safe_extract_zip(archive, target)
    marker.write_text(
        json.dumps(_zip_marker_payload(input_path), indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _find_screenshot(screenshots_dir: Path, task_name: str, step: int) -> Path | None:
    candidates = [
        screenshots_dir / f"{task_name}-0-{step}.png",
        screenshots_dir / f"{task_name}-0-{step - 1}.png",
        screenshots_dir / f"{step}.png",
        screenshots_dir / f"{step - 1}.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _attempt_num_from_name(name: str) -> int | None:
    match = re.match(r"attempt_(\d+)$", name)
    return int(match.group(1)) if match else None


def _infer_task_attempt_dir(traj_path: Path, root: Path) -> TaskAttemptDir:
    task_path = traj_path.parent
    rel_parts = task_path.relative_to(root).parts

    if len(rel_parts) >= 3 and rel_parts[0] == "_attempt_trajs":
        attempt_num = _attempt_num_from_name(rel_parts[2])
        return TaskAttemptDir(
            task_name=rel_parts[1],
            label=f"Attempt {attempt_num or rel_parts[2]}",
            attempt_num=attempt_num,
            path=task_path,
        )

    attempt_num = _attempt_num_from_name(task_path.name)
    if attempt_num is not None and task_path.parent != root:
        return TaskAttemptDir(
            task_name=task_path.parent.name,
            label=f"Attempt {attempt_num}",
            attempt_num=attempt_num,
            path=task_path,
        )

    return TaskAttemptDir(
        task_name=task_path.name,
        label="Attempt 1",
        attempt_num=1,
        path=task_path,
    )


def _iter_task_attempt_dirs(traj_dir: Path) -> list[TaskAttemptDir]:
    attempts = []
    for traj_path in traj_dir.rglob("traj.json"):
        if ".hfd" in traj_path.parts or "_memgui_eval" in traj_path.parts:
            continue
        attempts.append(_infer_task_attempt_dir(traj_path, traj_dir))
    return sorted(attempts, key=lambda item: (item.task_name, item.attempt_num or 9999, str(item.path)))


def _score_from_result_text(result: str | None) -> float | None:
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


def _primary_attempt_index(attempts: list[dict[str, Any]]) -> int:
    best_index = 0
    best_score = -1.0
    for index, attempt in enumerate(attempts):
        score = _score_from_result_text(attempt.get("result"))
        if score is not None and score > best_score:
            best_score = score
            best_index = index
    return best_index


def bundle_mobileworld_run(
    traj_dir: Path,
    output: Path,
    *,
    with_screenshots: bool = False,
    video_base_url: str = "",
) -> None:
    if with_screenshots:
        from PIL import Image  # noqa: F401

    combined: dict[str, Any] = {}
    task_attempts: dict[str, list[dict[str, Any]]] = {}
    frames: list[Path] = []
    original_size: tuple[int, int] | None = None
    display_size: tuple[int, int] | None = None
    task_catalog = _load_legacy_task_catalog(traj_dir)
    attempt_dirs = _iter_task_attempt_dirs(traj_dir)
    _progress(
        f"Bundling {len(attempt_dirs)} task attempts from {traj_dir} "
        f"({'with' if with_screenshots else 'without'} screenshots)"
    )

    for attempt_index, attempt_info in enumerate(attempt_dirs, start=1):
        task_path = attempt_info.path
        task_name = attempt_info.task_name
        if "_backup_" in task_path.parts:
            continue
        if attempt_index == 1 or attempt_index % PROGRESS_EVERY == 0 or attempt_index == len(attempt_dirs):
            _progress(
                f"Reading attempt {attempt_index}/{len(attempt_dirs)}: "
                f"{task_name} {attempt_info.label}"
            )
        traj_file = task_path / "traj.json"
        traj_data = _load_json(traj_file)
        entry = traj_data.get("0", traj_data) if isinstance(traj_data, dict) else {}
        steps = entry.get("traj", []) if isinstance(entry, dict) else []
        if not isinstance(steps, list):
            continue
        fallback_goal = _task_goal_from_catalog(task_name, task_catalog)
        if fallback_goal:
            for step in steps:
                if isinstance(step, dict) and not step.get("task_goal"):
                    step["task_goal"] = fallback_goal

        screenshots_dir = task_path / "screenshots"
        if with_screenshots and screenshots_dir.is_dir():
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_num = int(step.get("step") or 0)
                img_path = _find_screenshot(screenshots_dir, task_name, step_num)
                if img_path:
                    if original_size is None:
                        from PIL import Image

                        with Image.open(img_path) as img:
                            original_size = img.size
                            target_w = SCREENSHOT_RESIZE_WIDTH + (SCREENSHOT_RESIZE_WIDTH % 2)
                            target_h = int(target_w * original_size[1] / original_size[0])
                            if target_h % 2:
                                target_h += 1
                            display_size = (target_w, target_h)
                    step["frame_index"] = len(frames)
                    frames.append(img_path)
                    if len(frames) % FRAME_PROGRESS_EVERY == 0:
                        _progress(f"Collected {len(frames)} screenshot frames")

        result = None
        result_file = task_path / "result.txt"
        if result_file.exists():
            result = result_file.read_text(encoding="utf-8").strip()

        task_attempts.setdefault(task_name, []).append({
            "label": attempt_info.label,
            "attempt_num": attempt_info.attempt_num,
            "traj": steps,
            "token_usage": entry.get("token_usage", {}) if isinstance(entry, dict) else {},
            "result": result,
        })

    for task_name, attempts in sorted(task_attempts.items()):
        primary_index = _primary_attempt_index(attempts)
        primary = attempts[primary_index]
        combined[task_name] = {
            "traj": primary.get("traj", []),
            "token_usage": primary.get("token_usage", {}),
            "result": primary.get("result"),
            "attempts": attempts,
            "attempt_count": len(attempts),
            "primary_attempt_index": primary_index,
        }

    video_ref = None
    video_revision = None
    if with_screenshots and frames:
        video_output = output.with_suffix("").with_suffix(".mp4")
        _progress(f"Encoding video from {len(frames)} frames -> {video_output}")
        _encode_video(frames, video_output, original_size)
        video_stat = video_output.stat()
        video_revision = f"{video_stat.st_size}-{video_stat.st_mtime_ns}"
        video_ref = (
            video_base_url.rstrip("/") + "/" + video_output.name
            if video_base_url
            else video_output.name
        )

    if with_screenshots and original_size and frames and display_size:
        combined["_meta"] = {
            "video_file": video_ref,
            "fps": VIDEO_FPS,
            "total_frames": len(frames),
            "video_revision": video_revision,
            "original_width": original_size[0],
            "original_height": original_size[1],
            "display_width": display_size[0],
            "display_height": display_size[1],
        }

    _ensure_dir(output.parent)
    json_bytes = json.dumps(combined, ensure_ascii=False).encode("utf-8")
    _progress(f"Writing bundled trajectory JSON -> {output}")
    with gzip.open(output, "wb") as file:
        file.write(json_bytes)

    _progress(
        f"{len(combined) - (1 if '_meta' in combined else 0)} tasks | "
        f"{len(json_bytes) / 1024:.0f} KB raw | {output.stat().st_size / 1024:.0f} KB gzipped -> {output}"
    )
    if video_ref:
        video_path = output.with_suffix("").with_suffix(".mp4")
        _progress(f"{len(frames)} frames -> {video_path.stat().st_size / 1024 / 1024:.1f} MB video -> {video_path}")
    _update_traj_manifest(output)


def _update_traj_manifest(output: Path) -> None:
    if output.parent.name != "trajs":
        return
    manifest = output.parent / "index.json"
    files = [f"trajs/{path.name}" for path in sorted(output.parent.glob("*.json.gz"))]
    manifest.write_text(
        json.dumps({"files": files}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _encode_video(frame_paths: list[Path], video_output: Path, original_size: tuple[int, int] | None) -> None:
    from PIL import Image

    tmpdir = Path(tempfile.mkdtemp(prefix="memgui_frames_"))
    try:
        _progress(f"Preparing {len(frame_paths)} frames for ffmpeg")
        target_w = SCREENSHOT_RESIZE_WIDTH
        if target_w % 2:
            target_w += 1
        target_h = None
        if original_size:
            target_h = int(target_w * original_size[1] / original_size[0])
            if target_h % 2:
                target_h += 1

        for index, src_path in enumerate(frame_paths):
            with Image.open(src_path) as img:
                if target_h is None:
                    target_h = int(target_w * img.height / img.width)
                    if target_h % 2:
                        target_h += 1
                resized = img.convert("RGB").resize((target_w, target_h), Image.LANCZOS)
                resized.save(tmpdir / f"{index:06d}.png", optimize=True)
            frame_count = index + 1
            if frame_count == 1 or frame_count % FRAME_PROGRESS_EVERY == 0 or frame_count == len(frame_paths):
                _progress(f"Prepared frame {frame_count}/{len(frame_paths)}")

        _ensure_dir(video_output.parent)
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(VIDEO_FPS),
            "-i",
            str(tmpdir / "%06d.png"),
            "-c:v",
            "libx264",
            "-g",
            "1",
            "-keyint_min",
            "1",
            "-sc_threshold",
            "0",
            "-bf",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            str(VIDEO_CRF),
            "-movflags",
            "+faststart",
            str(video_output),
        ]
        _progress("Running ffmpeg")
        subprocess.run(cmd, check=True, capture_output=True)
        _progress("ffmpeg finished")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def prepare_input(input_path: Path, converted_root: Path, attempt_num: int | None) -> Path:
    source_dir = extract_zip_if_needed(input_path)
    if has_mobileworld_tasks(source_dir):
        return source_dir
    attempts = discover_legacy_attempts(source_dir, attempt_num=attempt_num)
    if not attempts:
        attempt_desc = "legacy log.json files" if attempt_num is None else f"legacy attempt_{attempt_num} log.json files"
        raise ValueError(f"No MobileWorld traj.json or {attempt_desc} found under {source_dir}")
    output_dir = converted_root / source_dir.name
    return convert_legacy_run(source_dir, output_dir, attempt_num=attempt_num)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Trajectory run directory or .zip archive")
    parser.add_argument("-o", "--output", help="Output .json.gz path")
    parser.add_argument("--with-screenshots", action="store_true", help="Bundle screenshots into an MP4")
    parser.add_argument(
        "--attempt-num",
        type=int,
        default=0,
        help="Legacy attempt number to bundle. Use 0 to bundle all attempts.",
    )
    parser.add_argument(
        "--converted-root",
        default="traj_logs/_converted_mobileworld",
        help="Where legacy inputs are converted before bundling",
    )
    parser.add_argument(
        "--video-base-url",
        default="",
        help="Optional absolute base URL for MP4 files. By default MP4 paths are local relative filenames.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Error: {input_path} does not exist")

    output = Path(args.output) if args.output else Path("docs/trajs") / f"{input_path.stem}.json.gz"
    attempt_num = None if args.attempt_num <= 0 else args.attempt_num
    prepared_dir = prepare_input(input_path, Path(args.converted_root), attempt_num)
    bundle_mobileworld_run(
        prepared_dir,
        output,
        with_screenshots=args.with_screenshots,
        video_base_url=args.video_base_url,
    )


if __name__ == "__main__":
    main()
