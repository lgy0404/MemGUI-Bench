"""Bridge MobileWorld trajectories into MemGUI-Eval."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from mobile_world.tasks.memgui_registry import resolve_dataset_path

logger = logging.getLogger(__name__)


def _action_to_legacy(action: dict[str, Any]) -> list[Any]:
    action_type = action.get("action_type") or "unknown"
    detail: dict[str, Any] = {"detail_type": "raw", "detail": action}

    if action_type in {"click", "double_tap", "long_press"}:
        detail = {"detail_type": "coordinates", "detail": [action.get("x"), action.get("y")]}
    elif action_type in {"input_text", "answer", "ask_user"}:
        detail = {"detail_type": "text", "detail": action.get("text", "")}
    elif action_type in {"scroll", "swipe"}:
        detail = {"detail_type": "direction", "detail": action.get("direction", "")}
    elif action_type == "open_app":
        detail = {"detail_type": "app", "detail": action.get("app_name", "")}
    elif action_type == "drag":
        detail = {
            "detail_type": "coordinates",
            "detail": [
                action.get("start_x"),
                action.get("start_y"),
                action.get("end_x"),
                action.get("end_y"),
            ],
        }
    elif action_type in {"navigate_home", "navigate_back", "keyboard_enter", "wait", "finished"}:
        detail = {"detail_type": "status", "detail": action_type}

    return [action_type, detail]


def _load_mobileworld_traj(traj_dir: Path) -> list[dict[str, Any]]:
    traj_path = traj_dir / "traj.json"
    if not traj_path.exists():
        raise FileNotFoundError(f"MobileWorld trajectory not found: {traj_path}")

    with traj_path.open(encoding="utf-8") as file:
        raw = json.load(file)

    task_log = raw.get("0") if isinstance(raw, dict) else None
    if not isinstance(task_log, dict):
        raise ValueError(f"Unexpected MobileWorld trajectory format in {traj_path}")
    traj = task_log.get("traj", [])
    if not isinstance(traj, list):
        raise ValueError(f"Unexpected MobileWorld trajectory steps in {traj_path}")
    return traj


def prepare_memgui_eval_workspace(
    *,
    log_file_root: str,
    task_name: str,
    task_traj_dir: str,
    agent_name: str,
    attempt_num: int = 1,
) -> Path:
    """Create the legacy MemGUI-Eval workspace from MobileWorld logs."""

    root = Path(log_file_root)
    eval_root = root / "_memgui_eval"
    eval_root.mkdir(parents=True, exist_ok=True)

    dataset_path = resolve_dataset_path()
    results_csv = eval_root / "results.csv"
    if not results_csv.exists():
        shutil.copyfile(dataset_path, results_csv)

    target_dir = eval_root / task_name / agent_name / f"attempt_{attempt_num}"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    traj_dir = Path(task_traj_dir)
    traj = _load_mobileworld_traj(traj_dir)

    legacy_log = []
    screenshots_dir = traj_dir / "screenshots"
    for index, step_data in enumerate(traj):
        step = int(step_data.get("step") or index + 1)
        action = step_data.get("action") or {}
        legacy_log.append(
            {
                "step": step,
                "thought": step_data.get("prediction"),
                "action": _action_to_legacy(action),
                "mobileworld_action": action,
                "ask_user_response": step_data.get("ask_user_response"),
                "tool_call": step_data.get("tool_call"),
            }
        )

        screenshot = screenshots_dir / f"{task_name}-0-{step}.png"
        if screenshot.exists():
            # MemGUI-Eval expects the screenshot before step N at "N-1.png".
            shutil.copyfile(screenshot, target_dir / f"{step - 1}.png")

    with (target_dir / "log.json").open("w", encoding="utf-8") as file:
        json.dump(legacy_log, file, ensure_ascii=False, indent=2)

    return eval_root


def evaluate_memgui_trajectory(
    *,
    log_file_root: str,
    task_name: str,
    task_traj_dir: str,
    agent_name: str,
    attempt_num: int = 1,
    reasoning_mode: str = "direct",
    action_mode: str = "with_action",
) -> tuple[float, str]:
    """Run MemGUI-Eval over a MobileWorld-format trajectory."""

    eval_root = prepare_memgui_eval_workspace(
        log_file_root=log_file_root,
        task_name=task_name,
        task_traj_dir=task_traj_dir,
        agent_name=agent_name,
        attempt_num=attempt_num,
    )

    try:
        from memgui_eval.evaluator import memgui_evaluator

        result = memgui_evaluator(
            task_identifier=task_name,
            result_dir=str(eval_root),
            mode="full",
            agent=agent_name,
            attempt_num=attempt_num,
            reasoning_mode=reasoning_mode,
            action_mode=action_mode,
        )
    except Exception as exc:
        logger.exception(f"MemGUI-Eval failed for {task_name}")
        return 0.0, f"MemGUI-Eval error: {exc}"

    if isinstance(result, dict):
        decision = int(result.get("decision", result.get("final_result", -1)))
        reason = result.get("reason", "No reason provided.")
    else:
        decision = int(result)
        reason = f"MemGUI-Eval returned {result}"

    if decision == 1:
        return 1.0, reason
    if decision == 0:
        return 0.0, reason
    return 0.0, f"MemGUI-Eval returned error decision {decision}: {reason}"
