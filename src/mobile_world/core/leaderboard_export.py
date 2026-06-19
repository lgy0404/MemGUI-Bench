"""Export MemGUI-Bench runs in leaderboard submission format."""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from mobile_world.core.log_viewer.utils import (
    _get_attempt_prefixes,
    _get_metric_task_set,
    _is_evaluated_value,
    _is_success_value,
    _read_memgui_results_rows,
    _to_float,
    calculate_memgui_eval_metrics,
    get_all_trajectory_steps,
    get_memgui_task_metadata,
    get_screenshots,
    get_task_attempt_folder,
    get_task_folders,
    read_log_metadata,
)

METRICS_SUMMARY_FILE = "metrics_summary.json"
METRICS_SUMMARY_CSV = "metrics_summary.csv"
METRICS_HISTORY_FILE = "metrics_history.jsonl"


def _round(value: Any, digits: int = 1, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return default


def _task_id(row: dict[str, Any]) -> str:
    return str(row.get("task_identifier") or "").strip()


def _truthy_memory(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().upper() == "Y"


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _agent_name_from_results(fieldnames: list[str], fallback: str = "Unknown") -> str:
    for _, prefix in _get_attempt_prefixes(fieldnames):
        marker = "_attempt_"
        base = prefix.split(marker, 1)[0] if marker in prefix else prefix
        for suffix in ("_direct_with_action", "_with_action", "_no_action", "_text_action"):
            if base.endswith(suffix):
                return base[: -len(suffix)] or fallback
        return base or fallback
    for field in fieldnames:
        if field.endswith("_attempt_1_completion"):
            return field[: -len("_attempt_1_completion")] or fallback
        if field.endswith("_successful_attempts"):
            return field[: -len("_successful_attempts")] or fallback
    return fallback


def _leaderboard_filename(agent_name: str) -> str:
    filename = agent_name.strip().lower().replace(" ", "-").replace("_", "-")
    while "--" in filename:
        filename = filename.replace("--", "-")
    return f"{filename or 'unknown'}.json"


def _load_rows_for_run(log_root: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows, fieldnames = _read_memgui_results_rows(log_root)
    metadata = read_log_metadata(log_root)
    task_set = _get_metric_task_set(
        log_root,
        str(metadata.get("suite_family") or "memgui_bench"),
        get_task_folders(log_root),
    )
    if not task_set:
        task_set = [_task_id(row) for row in rows if _task_id(row)]

    task_lookup = set(task_set)
    filtered_rows = [row for row in rows if _task_id(row) in task_lookup]
    return filtered_rows, fieldnames, task_set


def _prefix_for_attempt(
    attempt_prefixes: list[tuple[int, str]],
    attempt: int,
) -> str | None:
    for attempt_num, prefix in attempt_prefixes:
        if attempt_num == attempt:
            return prefix
    return None


def _row_success(row: dict[str, Any], attempt_prefixes: list[tuple[int, str]], attempt: int) -> int:
    prefix = _prefix_for_attempt(attempt_prefixes, attempt)
    if not prefix:
        return 0
    return int(_is_success_value(row.get(f"{prefix}_evaluation")))


def _row_pass_at(row: dict[str, Any], attempt_prefixes: list[tuple[int, str]], k: int) -> int:
    return int(
        any(
            _row_success(row, attempt_prefixes, attempt) == 1
            for attempt in range(1, k + 1)
        )
    )


def _attempt_steps(log_root: str, task_name: str, attempt: int) -> int:
    folder = get_task_attempt_folder(log_root, task_name, attempt)
    return len(get_all_trajectory_steps(folder))


def _attempt_time(log_root: str, task_name: str, attempt: int) -> float:
    folder = get_task_attempt_folder(log_root, task_name, attempt)
    screenshots = get_screenshots(folder)
    if len(screenshots) < 2:
        return 0.0
    paths = [os.path.join(folder, subfolder, filename) for _, filename, subfolder in screenshots]
    try:
        mtimes = [os.path.getmtime(path) for path in paths]
    except OSError:
        return 0.0
    duration = max(mtimes) - min(mtimes)
    return duration if duration > 0 else 0.0


def _attempt_token_usage(log_root: str, task_name: str, attempt: int) -> tuple[int, int]:
    folder = get_task_attempt_folder(log_root, task_name, attempt)
    traj_path = os.path.join(folder, "traj.json")
    if not os.path.exists(traj_path):
        return 0, 0
    try:
        with open(traj_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0, 0

    token_usage = data.get("token_usage") if isinstance(data, dict) else None
    if token_usage is None and isinstance(data, dict) and data:
        first_value = data.get(next(iter(data)))
        if isinstance(first_value, dict):
            token_usage = first_value.get("token_usage")
    if not isinstance(token_usage, dict):
        return 0, 0
    return (
        int(token_usage.get("prompt_tokens") or 0),
        int(token_usage.get("completion_tokens") or 0),
    )


def _difficulty_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "1": "easy",
        "easy": "easy",
        "简单": "easy",
        "2": "medium",
        "medium": "medium",
        "中等": "medium",
        "3": "hard",
        "hard": "hard",
        "困难": "hard",
    }
    return mapping.get(text, text)


def calculate_leaderboard_metrics(log_root: str, max_attempts: int | None = None) -> dict[str, Any]:
    """Calculate v1-compatible MemGUI metrics from an existing MobileWorld log root."""
    rows, fieldnames, task_set = _load_rows_for_run(log_root)
    if not rows or not fieldnames:
        return {}

    attempt_prefixes = _get_attempt_prefixes(fieldnames)
    if not attempt_prefixes:
        return {}

    inferred_max_attempt = max(attempt for attempt, _ in attempt_prefixes)
    max_attempts = max_attempts or inferred_max_attempt
    max_attempts = max(1, min(max_attempts, inferred_max_attempt))
    agent_name = _agent_name_from_results(
        fieldnames,
        fallback=str(read_log_metadata(log_root).get("agent_type") or "Unknown"),
    )

    task_lookup = set(task_set)
    rows = [row for row in rows if _task_id(row) in task_lookup]
    total_tasks = len(task_set) or len(rows)
    memory_rows = [row for row in rows if _truthy_memory(row.get("requires_ui_memory"))]
    standard_rows = [row for row in rows if not _truthy_memory(row.get("requires_ui_memory"))]

    metrics: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "session": os.path.basename(os.path.normpath(log_root)),
        "agent": agent_name,
        "max_attempts": max_attempts,
        "total_tasks": total_tasks,
        "memory_tasks": len(
            [
                task_name
                for task_name in task_set
                if get_memgui_task_metadata(task_name).get("requires_ui_memory")
            ]
        ),
        "standard_tasks": len(
            [
                task_name
                for task_name in task_set
                if not get_memgui_task_metadata(task_name).get("requires_ui_memory")
            ]
        ),
    }

    executed_tasks = sum(1 for task_name in task_set if _attempt_steps(log_root, task_name, 1) > 0)
    attempt1_prefix = _prefix_for_attempt(attempt_prefixes, 1)
    evaluated_tasks = 0
    if attempt1_prefix:
        evaluated_tasks = sum(
            1
            for row in rows
            if _is_evaluated_value(row.get(f"{attempt1_prefix}_evaluation"))
        )
    metrics["executed_tasks"] = int(executed_tasks)
    metrics["evaluated_tasks"] = int(evaluated_tasks)

    for k in range(1, max_attempts + 1):
        pass_count = sum(_row_pass_at(row, attempt_prefixes, k) for row in rows)
        mem_count = sum(_row_pass_at(row, attempt_prefixes, k) for row in memory_rows)
        std_count = sum(_row_pass_at(row, attempt_prefixes, k) for row in standard_rows)
        metrics[f"pass_at_{k}_count"] = int(pass_count)
        metrics[f"pass_at_{k}_rate"] = pass_count / total_tasks * 100 if total_tasks else 0.0
        metrics[f"pass_at_{k}_memory_count"] = int(mem_count)
        metrics[f"pass_at_{k}_memory_rate"] = (
            mem_count / len(memory_rows) * 100 if memory_rows else 0.0
        )
        metrics[f"pass_at_{k}_standard_count"] = int(std_count)
        metrics[f"pass_at_{k}_standard_rate"] = (
            std_count / len(standard_rows) * 100 if standard_rows else 0.0
        )

    overall = calculate_memgui_eval_metrics(log_root, total_tasks, task_set)
    metrics["avg_irr"] = overall.get("avg_irr", 0.0)
    metrics["irr_count"] = overall.get("irr_count", 0)
    metrics["mtpr"] = overall.get("mtpr", 0.0)
    metrics["frr"] = overall.get("frr", 0.0)
    metrics["n_failed_1"] = overall.get("n_failed_1", 0)
    for attempt, count in (overall.get("recovery_counts") or {}).items():
        metrics[f"recovery_at_{attempt}"] = count

    for k in range(1, max_attempts + 1):
        passed_rows = [row for row in rows if _row_pass_at(row, attempt_prefixes, k)]
        step_ratios = []
        for row in passed_rows:
            task_name = _task_id(row)
            golden_steps = get_memgui_task_metadata(task_name).get("golden_steps")
            if isinstance(golden_steps, int) and golden_steps > 0:
                steps = _attempt_steps(log_root, task_name, 1)
                if steps > 0:
                    step_ratios.append(steps / golden_steps)
        metrics[f"step_ratio_at_{k}"] = (
            sum(step_ratios) / len(step_ratios) if step_ratios else 0.0
        )

        total_steps = 0
        total_time = 0.0
        total_cost = 0.0
        for task_name in task_set:
            for attempt in range(1, k + 1):
                steps = _attempt_steps(log_root, task_name, attempt)
                if steps <= 0:
                    continue
                total_steps += steps
                total_time += _attempt_time(log_root, task_name, attempt)
                prompt_tokens, completion_tokens = _attempt_token_usage(
                    log_root,
                    task_name,
                    attempt,
                )
                total_cost += (
                    (prompt_tokens / 1_000_000) * 1.25
                    + (completion_tokens / 1_000_000) * 10
                )
        metrics[f"time_per_step_at_{k}"] = total_time / total_steps if total_steps else 0.0
        metrics[f"cost_per_step_at_{k}"] = total_cost / total_steps if total_steps else 0.0

    for row in rows:
        task_name = _task_id(row)
        metadata = get_memgui_task_metadata(task_name)
        diff = _difficulty_key(row.get("task_difficulty") or metadata.get("difficulty"))
        if diff in {"easy", "medium", "hard"}:
            diff_num = {"easy": "1", "medium": "2", "hard": "3"}[diff]
            metrics[f"count_diff_{diff_num}"] = metrics.get(f"count_diff_{diff_num}", 0) + 1
        num_apps = _to_int(row.get("num_apps")) or _to_int(metadata.get("num_apps"))
        if num_apps in {1, 2, 3, 4}:
            metrics[f"count_apps_{num_apps}"] = metrics.get(f"count_apps_{num_apps}", 0) + 1

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        task_name = _task_id(row)
        metadata = get_memgui_task_metadata(task_name)
        diff = _difficulty_key(row.get("task_difficulty") or metadata.get("difficulty"))
        diff_num = {"easy": "1", "medium": "2", "hard": "3"}.get(diff)
        if diff_num:
            grouped.setdefault(f"diff_{diff_num}", []).append(row)
        num_apps = _to_int(row.get("num_apps")) or _to_int(metadata.get("num_apps"))
        if num_apps in {1, 2, 3, 4}:
            grouped.setdefault(f"apps_{num_apps}", []).append(row)

    for group_key, group_rows in grouped.items():
        denominator = len(group_rows)
        for k in range(1, max_attempts + 1):
            passed = sum(_row_pass_at(row, attempt_prefixes, k) for row in group_rows)
            metrics[f"pass_at_{k}_{group_key}"] = (
                passed / denominator * 100 if denominator else 0.0
            )
        irr_values = []
        if attempt1_prefix:
            for row in group_rows:
                if not _truthy_memory(row.get("requires_ui_memory")):
                    continue
                irr_value = _to_float(row.get(f"{attempt1_prefix}_irr_percentage"))
                if irr_value is not None:
                    irr_values.append(irr_value)
        metrics[f"irr_{group_key}"] = sum(irr_values) / len(irr_values) if irr_values else 0.0

    badcase_counter: Counter[str] = Counter()
    for attempt, prefix in attempt_prefixes:
        if attempt > max_attempts:
            continue
        badcase_col = f"{prefix}_badcase_category"
        if badcase_col not in fieldnames:
            continue
        for row in rows:
            if _is_success_value(row.get(f"{prefix}_evaluation")):
                continue
            category = str(row.get(badcase_col) or "").strip()
            if category:
                badcase_counter[f"badcase_att{attempt}_{category}"] += 1
    metrics.update(badcase_counter)

    return metrics


def generate_leaderboard_result(metrics: dict[str, Any], agent_name: str | None = None) -> dict[str, Any]:
    """Generate docs/data/agents-compatible JSON from calculated metrics."""
    agent_name = agent_name or str(metrics.get("agent") or "Unknown")
    cross_app = {}
    for app_count in [1, 2, 3, 4]:
        app_key = f"apps_{app_count}"
        cross_app[f"app{app_count}"] = {
            "p1": _round(metrics.get(f"pass_at_1_{app_key}"), 1, 0.0),
            "p3": _round(metrics.get(f"pass_at_3_{app_key}"), 1, 0.0),
            "irr": _round(metrics.get(f"irr_{app_key}"), 1, 0.0),
        }

    difficulty = {}
    for diff_num, diff_name in {"1": "easy", "2": "medium", "3": "hard"}.items():
        diff_key = f"diff_{diff_num}"
        difficulty[diff_name] = {
            "p1": _round(metrics.get(f"pass_at_1_{diff_key}"), 1, 0.0),
            "p3": _round(metrics.get(f"pass_at_3_{diff_key}"), 1, 0.0),
            "irr": _round(metrics.get(f"irr_{diff_key}"), 2, 0.0),
        }

    step_ratio = metrics.get("step_ratio_at_1")
    time_per_step = metrics.get("time_per_step_at_1")
    cost_per_step = metrics.get("cost_per_step_at_1")
    step_ratio_p3 = metrics.get("step_ratio_at_3", step_ratio)
    time_per_step_p3 = metrics.get("time_per_step_at_3", time_per_step)
    cost_per_step_p3 = metrics.get("cost_per_step_at_3", cost_per_step)

    return {
        "name": agent_name,
        "backbone": "-",
        "type": "",
        "institution": "",
        "date": "",
        "paperLink": "",
        "codeLink": "",
        "hasUITree": False,
        "hasLongTermMemory": False,
        "crossApp": cross_app,
        "difficulty": difficulty,
        "avg": {
            "p1": _round(metrics.get("pass_at_1_rate"), 1, 0.0),
            "p3": _round(metrics.get("pass_at_3_rate"), 1, 0.0),
        },
        "metrics": {
            "shortTerm": {
                "irr": _round(metrics.get("avg_irr"), 1, 0.0),
                "mtpr": _round(metrics.get("mtpr"), 2, 0.0),
                "stepRatio": _round(step_ratio, 2, None) if step_ratio else None,
                "timePerStep": _round(time_per_step, 1, 0.0),
                "costPerStep": _round(cost_per_step, 4, None) if cost_per_step else None,
            },
            "longTerm": {
                "frr": _round(metrics.get("frr"), 1, 0.0),
                "stepRatio": _round(step_ratio_p3, 2, None) if step_ratio_p3 else None,
                "timePerStep": _round(time_per_step_p3, 1, 0.0),
                "costPerStep": _round(cost_per_step_p3, 4, None) if cost_per_step_p3 else None,
            },
        },
    }


def save_leaderboard_outputs(
    log_root: str,
    max_attempts: int | None = None,
    agent_name: str | None = None,
    trigger: str = "Final Summary",
) -> tuple[dict[str, Any], str] | None:
    """Save metrics summary files and the leaderboard JSON in the log root."""
    metrics = calculate_leaderboard_metrics(log_root, max_attempts=max_attempts)
    if not metrics:
        logger.warning("No MemGUI metrics could be calculated for {}", log_root)
        return None

    metrics["trigger"] = trigger
    agent_name = agent_name or str(metrics.get("agent") or "Unknown")
    output_dir = Path(log_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_json = output_dir / METRICS_SUMMARY_FILE
    metrics_json.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    metrics_csv = output_dir / METRICS_SUMMARY_CSV
    with metrics_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(metrics.keys()))
        writer.writeheader()
        writer.writerow(metrics)

    history_path = output_dir / METRICS_HISTORY_FILE
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")

    leaderboard = generate_leaderboard_result(metrics, agent_name=agent_name)
    leaderboard_path = output_dir / _leaderboard_filename(agent_name)
    leaderboard_path.write_text(
        json.dumps(leaderboard, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return metrics, str(leaderboard_path)
