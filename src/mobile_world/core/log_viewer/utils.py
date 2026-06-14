"""Utility functions for log viewer."""

import ast
import csv
import json
import os
import re
import time

from loguru import logger

from mobile_world.core.api.info import get_task_registry

# Global state for log root (could be enhanced with proper session management)
_log_root_state: dict[str, str] = {}
_task_registries: dict[str, object] = {}
_ATTEMPT_EVAL_RE = re.compile(r"^(?P<prefix>.+_attempt_(?P<attempt>\d+))_evaluation$")
MEMGUI_DIFFICULTY_TAGS = {
    "1": "Difficulty: Easy",
    "2": "Difficulty: Medium",
    "3": "Difficulty: Hard",
}
_MEMGUI_DIFFICULTY_ALIASES = {
    "1": "1",
    "easy": "1",
    "simple": "1",
    "low": "1",
    "简单": "1",
    "2": "2",
    "medium": "2",
    "middle": "2",
    "normal": "2",
    "中等": "2",
    "3": "3",
    "hard": "3",
    "difficult": "3",
    "high": "3",
    "困难": "3",
}
STALE_TASK_SECONDS = 600


def parse_result_file(result_file: str) -> tuple[float | None, str | None]:
    """Parse a MobileWorld result.txt file without importing the runtime client."""
    with open(result_file) as f:
        lines = f.readlines()
    if lines and "score:" in lines[0]:
        score = float(lines[0].split("score:", 1)[1].strip())
    else:
        score = None
    reason = lines[1].strip() if len(lines) > 1 else None
    return score, reason


def _clean_csv_value(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def _to_float(value) -> float | None:
    text = _clean_csv_value(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    return int(number)


def _memgui_results_csv_path(log_root: str) -> str:
    return os.path.join(log_root, "_memgui_eval", "results.csv")


def _read_memgui_results_rows(log_root: str) -> tuple[list[dict], list[str]]:
    csv_path = _memgui_results_csv_path(log_root)
    if not os.path.exists(csv_path):
        return [], []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader), reader.fieldnames or []
    except (OSError, csv.Error) as e:
        logger.warning(f"Error reading MemGUI results.csv in {log_root}: {e}")
        return [], []


def _read_latest_eval_report_metadata(log_root: str) -> dict:
    if not log_root or not os.path.isdir(log_root):
        return {}
    report_paths = [
        os.path.join(log_root, item)
        for item in os.listdir(log_root)
        if item.startswith("eval_report_") and item.endswith(".json")
    ]
    if not report_paths:
        return {}
    latest_path = max(report_paths, key=lambda path: os.path.getmtime(path))
    try:
        with open(latest_path) as f:
            report = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Error reading eval report metadata in {latest_path}: {e}")
        return {}
    metadata = report.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _get_attempt_prefixes(fieldnames: list[str]) -> list[tuple[int, str]]:
    prefixes: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for field in fieldnames:
        match = _ATTEMPT_EVAL_RE.match(field)
        if not match:
            continue
        attempt = int(match.group("attempt"))
        prefix = match.group("prefix")
        item = (attempt, prefix)
        if item not in seen:
            prefixes.append(item)
            seen.add(item)
    return sorted(prefixes, key=lambda item: (item[0], item[1]))


def _is_success_value(value) -> bool:
    return _clean_csv_value(value).upper() == "S"


def _is_evaluated_value(value) -> bool:
    return _clean_csv_value(value).upper() in {"S", "F", "E"}


def _metadata_pass_at_k(log_root: str) -> int:
    try:
        return max(1, int(read_log_metadata(log_root).get("pass_at_k") or 1))
    except (TypeError, ValueError):
        return 1


def get_log_root_state() -> dict[str, str]:
    """Get the global log root state."""
    return _log_root_state


def read_log_metadata(log_root: str) -> dict:
    """Read metadata.json from a log root directory.

    Returns a dict with at minimum {"suite_family": "memgui_bench"}.
    Falls back to defaults if file doesn't exist (backward compat).
    """
    defaults = {"suite_family": "memgui_bench", "seed": None}
    data = dict(defaults)
    if not log_root:
        return data

    report_metadata = _read_latest_eval_report_metadata(log_root)
    for key, value in report_metadata.items():
        if value not in (None, ""):
            data[key] = value

    metadata_path = os.path.join(log_root, "metadata.json")
    if not os.path.exists(metadata_path):
        return data
    try:
        with open(metadata_path) as f:
            file_data = json.load(f)
        data.update(file_data)
        for key, value in report_metadata.items():
            if data.get(key) in (None, "") and value not in (None, ""):
                data[key] = value
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Error reading metadata.json in {log_root}: {e}")
        return data


def is_valid_trajectory_dir(path: str) -> bool:
    """Check if a directory is a valid trajectory log directory.

    A valid trajectory directory contains either:
    - Task folders with trajectory data (standard mode)
    - User trajectory folders (id_X/user_task structure)
    """
    if not path or not os.path.exists(path) or not os.path.isdir(path):
        return False

    # Check for user trajectory structure
    if is_user_trajectory_log(path):
        return True

    # Check for standard task folders with traj.json
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        if os.path.isdir(item_path) and "_backup_" not in item:
            traj_file = os.path.join(item_path, "traj.json")
            if os.path.exists(traj_file):
                return True

    return False


def get_child_trajectory_dirs(parent_path: str) -> list[str]:
    """Get all valid trajectory directories within a parent directory.

    Returns a list of directory names (not full paths) that are valid trajectory dirs.
    """
    if not parent_path or not os.path.exists(parent_path) or not os.path.isdir(parent_path):
        return []

    valid_dirs = []
    try:
        for item in os.listdir(parent_path):
            item_path = os.path.join(parent_path, item)
            if os.path.isdir(item_path) and is_valid_trajectory_dir(item_path):
                valid_dirs.append(item)
    except PermissionError:
        pass

    return sorted(valid_dirs)


def get_registry(suite_family: str = "memgui_bench"):
    """Get or initialize the task registry for a suite family."""
    global _task_registries
    if suite_family not in _task_registries:
        try:
            if suite_family == "android_world":
                from mobile_world.tasks.aw_registry import AWTaskRegistry
                _task_registries[suite_family] = AWTaskRegistry()
            elif suite_family == "memgui_bench":
                _task_registries[suite_family] = get_task_registry("memgui_bench")
            elif suite_family == "mobile_world":
                _task_registries[suite_family] = get_task_registry("mobile_world")
            else:
                # For unknown suite families (e.g. "user_task"), no registry
                return None
        except Exception as e:
            logger.error(f"Failed to load task registry for {suite_family}: {e}")
            return None
    return _task_registries[suite_family]


def get_task_tags(task_name: str, suite_family: str = "memgui_bench") -> list[str]:
    """Get tags for a specific task from the registry."""
    registry = get_registry(suite_family)
    if not registry:
        return []
    try:
        if registry.has_task(task_name):
            task = registry.get_task(task_name)
            if hasattr(task, "task_tags"):
                return sorted(task.task_tags)
    except Exception:
        pass
    return []


def _memgui_difficulty_tag(difficulty: str | None) -> str | None:
    difficulty_id = (difficulty or "").strip()
    return MEMGUI_DIFFICULTY_TAGS.get(difficulty_id)


def _normalize_memgui_difficulties(value: str | None) -> set[str]:
    if not value:
        return set()
    difficulties: set[str] = set()
    for raw_item in str(value).split(","):
        item = raw_item.strip().lower()
        if not item:
            continue
        normalized = _MEMGUI_DIFFICULTY_ALIASES.get(item)
        if normalized:
            difficulties.add(normalized)
    return difficulties


def _is_memgui_category_tag(tag: str) -> bool:
    return ":" in tag


def _memgui_tag_sort_key(tag: str) -> tuple[int, int | str]:
    difficulty_order = {label: index for index, label in enumerate(MEMGUI_DIFFICULTY_TAGS.values())}
    if tag in difficulty_order:
        return (0, difficulty_order[tag])
    if _is_memgui_category_tag(tag):
        return (2, tag.lower())
    return (1, tag.lower())


def get_task_filter_tags(task_name: str, suite_family: str = "memgui_bench") -> list[str]:
    """Get tags used by the viewer filters, including MemGUI difficulty tags."""
    tags = list(get_task_tags(task_name, suite_family=suite_family))
    if suite_family == "memgui_bench":
        difficulty_tag = _memgui_difficulty_tag(
            str(get_memgui_task_metadata(task_name).get("difficulty") or "")
        )
        if difficulty_tag:
            tags.append(difficulty_tag)
    return sorted(set(tags), key=_memgui_tag_sort_key if suite_family == "memgui_bench" else str.lower)


def _parse_memgui_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return [value]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return [str(parsed)]


def _parse_bool_flag(value: str | None) -> bool:
    return (value or "").strip().upper() == "Y"


def get_memgui_task_metadata(task_name: str) -> dict:
    """Return MemGUI-specific metadata for a task."""
    registry = get_registry("memgui_bench")
    if not registry:
        return {}
    try:
        if not registry.has_task(task_name):
            return {}
        task = registry.get_task(task_name)
        record = task.record
    except Exception:
        return {}

    try:
        golden_steps = int(float(record.golden_steps))
    except ValueError:
        golden_steps = None

    return {
        "apps": _parse_memgui_list(record.task_app),
        "num_apps": record.num_apps,
        "is_cross_app": _parse_bool_flag(record.is_cross_app),
        "categories": _parse_memgui_list(record.category),
        "requires_ui_memory": _parse_bool_flag(record.requires_ui_memory),
        "shortcut_potential": record.shortcut_potential,
        "output_type": record.output_type,
        "golden_steps": golden_steps,
        "difficulty": record.task_difficulty,
        "language": record.task_language,
    }


def get_memgui_eval_info(log_root: str, task_name: str) -> dict:
    """Return MemGUI-Eval CSV details for one task."""
    rows, fieldnames = _read_memgui_results_rows(log_root)
    if not rows:
        return {}

    row = next((item for item in rows if item.get("task_identifier") == task_name), None)
    if not row:
        return {}

    attempts = []
    successful_attempts: list[int] = []
    for attempt, prefix in _get_attempt_prefixes(fieldnames):
        evaluation = _clean_csv_value(row.get(f"{prefix}_evaluation"))
        if not evaluation:
            continue
        is_success = evaluation.upper() == "S"
        if is_success:
            successful_attempts.append(attempt)
        attempts.append(
            {
                "attempt": attempt,
                "prefix": prefix,
                "evaluation": evaluation,
                "success": is_success,
                "details": _clean_csv_value(row.get(f"{prefix}_details")),
                "method": _clean_csv_value(row.get(f"{prefix}_evaluation_method")),
                "failure_step": _clean_csv_value(row.get(f"{prefix}_failure_step")),
                "irr_percentage": _to_float(row.get(f"{prefix}_irr_percentage")),
                "irr_total_units": _clean_csv_value(row.get(f"{prefix}_irr_total_units")),
                "irr_correct_units": _clean_csv_value(row.get(f"{prefix}_irr_correct_units")),
                "irr_reason": _clean_csv_value(row.get(f"{prefix}_irr_reason")),
                "irr_method": _clean_csv_value(row.get(f"{prefix}_irr_method")),
                "badcase_category": _clean_csv_value(row.get(f"{prefix}_badcase_category")),
                "badcase_confidence": _clean_csv_value(row.get(f"{prefix}_badcase_confidence")),
                "badcase_key_failure_point": _clean_csv_value(
                    row.get(f"{prefix}_badcase_key_failure_point")
                ),
                "badcase_suggested_improvement": _clean_csv_value(
                    row.get(f"{prefix}_badcase_suggested_improvement")
                ),
            }
        )

    evaluating_attempts = [
        item["attempt"]
        for item in get_memgui_evaluating_attempts(log_root, task_name=task_name)
    ]
    latest_attempt = attempts[-1] if attempts else {}
    max_attempt = max(
        max((attempt["attempt"] for attempt in attempts), default=0),
        max(evaluating_attempts, default=0),
        _metadata_pass_at_k(log_root),
    )
    pass_at = {
        k: any(attempt <= k for attempt in successful_attempts)
        for k in range(1, max(max_attempt, 1) + 1)
    }

    return {
        "attempts": attempts,
        "latest": latest_attempt,
        "successful_attempts": successful_attempts,
        "evaluating_attempts": evaluating_attempts,
        "pass_at": pass_at,
        "max_attempt": max_attempt,
    }


def _has_memgui_attempt_evaluation(
    row: dict | None,
    fieldnames: list[str],
    attempt_num: int,
    agent_name: str | None = None,
) -> bool:
    if not row:
        return False
    agent_prefix = f"{agent_name}_" if agent_name else None
    for field in fieldnames:
        match = _ATTEMPT_EVAL_RE.match(field)
        if not match or int(match.group("attempt")) != attempt_num:
            continue
        if agent_prefix and not field.startswith(agent_prefix):
            continue
        if _is_evaluated_value(row.get(field)):
            return True
    return False


def get_memgui_evaluating_attempts(
    log_root: str,
    task_name: str | None = None,
    attempt_num: int | None = None,
    task_set: list[str] | None = None,
) -> list[dict]:
    """Return MemGUI-Eval workspaces that are active/pending a CSV decision.

    A trajectory counts as evaluating once its compatibility workspace exists
    under `_memgui_eval/`, but before that attempt has an evaluation row in
    `results.csv`. A MobileWorld-facing `result.txt` may already exist with a
    `MemGUI-Eval error` placeholder, so the CSV decision is the source of truth.
    """
    eval_root = os.path.join(log_root, "_memgui_eval")
    if not os.path.isdir(eval_root):
        return []

    rows, fieldnames = _read_memgui_results_rows(log_root)
    row_by_task = {row.get("task_identifier", ""): row for row in rows}
    task_set_lookup = set(task_set or [])
    evaluating = []

    try:
        task_names = sorted(os.listdir(eval_root))
    except OSError:
        return []

    for eval_task_name in task_names:
        if task_name and eval_task_name != task_name:
            continue
        if task_set_lookup and eval_task_name not in task_set_lookup:
            continue
        task_eval_dir = os.path.join(eval_root, eval_task_name)
        if not os.path.isdir(task_eval_dir):
            continue

        try:
            agent_names = sorted(os.listdir(task_eval_dir))
        except OSError:
            continue

        for agent_name in agent_names:
            agent_dir = os.path.join(task_eval_dir, agent_name)
            if not os.path.isdir(agent_dir):
                continue
            try:
                attempt_dirs = sorted(os.listdir(agent_dir))
            except OSError:
                continue

            for attempt_dir_name in attempt_dirs:
                if not attempt_dir_name.startswith("attempt_"):
                    continue
                try:
                    workspace_attempt_num = int(attempt_dir_name.split("_", 1)[1])
                except (IndexError, ValueError):
                    continue
                if attempt_num is not None and workspace_attempt_num != attempt_num:
                    continue

                workspace_dir = os.path.join(agent_dir, attempt_dir_name)
                if not os.path.isdir(workspace_dir):
                    continue
                if not os.path.exists(os.path.join(workspace_dir, "log.json")):
                    continue

                task_row = row_by_task.get(eval_task_name)
                if _has_memgui_attempt_evaluation(
                    task_row, fieldnames, workspace_attempt_num, agent_name
                ):
                    continue

                evaluating.append(
                    {
                        "task_name": eval_task_name,
                        "agent_name": agent_name,
                        "attempt": workspace_attempt_num,
                        "workspace": workspace_dir,
                    }
                )

    return evaluating


def get_memgui_attempt_statuses(memgui_eval_info: dict) -> list[dict]:
    """Return per-attempt display states for MemGUI pass@k runs."""
    if not memgui_eval_info:
        return []

    attempts_by_num = {}
    for item in memgui_eval_info.get("attempts") or []:
        attempt_num = _to_int(item.get("attempt"))
        if attempt_num is not None:
            attempts_by_num[attempt_num] = item

    max_attempt = _to_int(memgui_eval_info.get("max_attempt"))
    if max_attempt is None:
        max_attempt = max(attempts_by_num, default=1)
    max_attempt = max(max_attempt, 1)

    successful_attempts = [
        attempt
        for attempt in (_to_int(item) for item in memgui_eval_info.get("successful_attempts") or [])
        if attempt is not None
    ]
    first_success = min(successful_attempts) if successful_attempts else None
    evaluating_attempts = {
        attempt
        for attempt in (_to_int(item) for item in memgui_eval_info.get("evaluating_attempts") or [])
        if attempt is not None
    }

    statuses = []
    for attempt_num in range(1, max_attempt + 1):
        attempt_info = attempts_by_num.get(attempt_num)
        if attempt_info:
            evaluation = _clean_csv_value(attempt_info.get("evaluation"))
            evaluation_upper = evaluation.upper()
            if attempt_info.get("success") or evaluation_upper == "S":
                label = "Pass"
                state = "success"
            elif evaluation_upper == "F":
                label = "Fail"
                state = "danger"
            elif evaluation_upper == "E":
                label = "Error"
                state = "danger"
            else:
                label = evaluation or "Done"
                state = "info"
        elif attempt_num in evaluating_attempts:
            label = "Evaluating"
            state = "info"
        elif first_success is not None and attempt_num > first_success:
            label = "Skipped"
            state = "info"
        else:
            label = "Pending"
            state = "pending"

        statuses.append({"attempt": attempt_num, "label": label, "state": state})

    return statuses


def calculate_memgui_eval_metrics(
    log_root: str,
    total_tasks: int,
    task_set: list[str] | None = None,
) -> dict:
    """Calculate MemGUI leaderboard-style metrics from `_memgui_eval/results.csv`."""
    rows, fieldnames = _read_memgui_results_rows(log_root)
    attempt_prefixes = _get_attempt_prefixes(fieldnames)
    evaluating_attempts = get_memgui_evaluating_attempts(log_root, task_set=task_set)
    max_attempt = max(
        max((attempt for attempt, _ in attempt_prefixes), default=1),
        max((item["attempt"] for item in evaluating_attempts), default=1),
        _metadata_pass_at_k(log_root),
    )
    task_set_lookup = set(task_set or [])
    if task_set_lookup:
        rows = [row for row in rows if row.get("task_identifier", "") in task_set_lookup]

    pass_counts = {k: 0 for k in range(1, max_attempt + 1)}
    pass_memory_counts = {k: 0 for k in range(1, max_attempt + 1)}
    pass_standard_counts = {k: 0 for k in range(1, max_attempt + 1)}
    task_attempt_results: dict[str, dict[int, bool]] = {}

    memory_total = 0
    standard_total = 0
    evaluated_count = 0
    irr_sum = 0.0
    irr_count = 0

    if task_set_lookup:
        for task_id in task_set or []:
            metadata = get_memgui_task_metadata(task_id)
            if metadata.get("requires_ui_memory"):
                memory_total += 1
            else:
                standard_total += 1

    for row in rows:
        task_id = row.get("task_identifier", "")
        if not task_id:
            continue
        is_memory_task = _parse_bool_flag(row.get("requires_ui_memory"))
        if not task_set_lookup:
            if is_memory_task:
                memory_total += 1
            else:
                standard_total += 1

        attempt_results: dict[int, bool] = {}
        first_success_attempt: int | None = None
        has_evaluation = False
        for attempt, prefix in attempt_prefixes:
            evaluation_value = row.get(f"{prefix}_evaluation")
            if _is_evaluated_value(evaluation_value):
                has_evaluation = True
            success = _is_success_value(evaluation_value)
            attempt_results[attempt] = success
            if success and first_success_attempt is None:
                first_success_attempt = attempt

            if is_memory_task and attempt == 1:
                irr_value = _to_float(row.get(f"{prefix}_irr_percentage"))
                if irr_value is not None:
                    irr_sum += irr_value
                    irr_count += 1

        if has_evaluation:
            evaluated_count += 1
        task_attempt_results[task_id] = attempt_results

        if first_success_attempt is not None:
            for k in range(first_success_attempt, max_attempt + 1):
                pass_counts[k] += 1
                if is_memory_task:
                    pass_memory_counts[k] += 1
                else:
                    pass_standard_counts[k] += 1

    denominator = total_tasks if total_tasks > 0 else len(rows)
    pass_rates = {
        k: (pass_counts[k] / denominator * 100 if denominator > 0 else 0.0)
        for k in pass_counts
    }
    pass_memory_rates = {
        k: (pass_memory_counts[k] / memory_total * 100 if memory_total > 0 else 0.0)
        for k in pass_memory_counts
    }
    pass_standard_rates = {
        k: (pass_standard_counts[k] / standard_total * 100 if standard_total > 0 else 0.0)
        for k in pass_standard_counts
    }

    n_failed_1 = 0
    recovery_counts = {k: 0 for k in range(2, max_attempt + 1)}
    for results in task_attempt_results.values():
        if results.get(1, False):
            continue
        if 1 in results:
            n_failed_1 += 1
        for k in range(2, max_attempt + 1):
            if results.get(k, False) and all(not results.get(i, False) for i in range(1, k)):
                recovery_counts[k] += 1
                break

    weighted_recoveries = sum(
        (1.0 / (2 ** (k - 2))) * count for k, count in recovery_counts.items()
    )
    frr = weighted_recoveries / n_failed_1 * 100 if n_failed_1 > 0 else 0.0
    mtpr = (
        pass_memory_rates.get(1, 0.0) / pass_standard_rates.get(1, 0.0)
        if pass_standard_rates.get(1, 0.0) > 0
        else 0.0
    )

    return {
        "max_attempt": max_attempt,
        "evaluated_count": evaluated_count,
        "memory_total": memory_total,
        "standard_total": standard_total,
        "pass_counts": pass_counts,
        "pass_rates": pass_rates,
        "pass_memory_counts": pass_memory_counts,
        "pass_memory_rates": pass_memory_rates,
        "pass_standard_counts": pass_standard_counts,
        "pass_standard_rates": pass_standard_rates,
        "avg_irr": irr_sum / irr_count if irr_count else 0.0,
        "irr_count": irr_count,
        "mtpr": mtpr,
        "frr": frr,
        "recovery_counts": recovery_counts,
        "n_failed_1": n_failed_1,
    }


def count_ask_user_actions(trajectory_steps: list[dict]) -> int:
    """Count the number of ask_user actions in a trajectory."""
    count = 0
    for step in trajectory_steps:
        action = step.get("action", {})
        action_type = action.get("action_type", "")
        if action_type == "ask_user":
            count += 1
    return count


def count_mcp_actions(trajectory_steps: list[dict]) -> int:
    """Count the number of MCP tool calls in a trajectory."""
    count = 0
    for step in trajectory_steps:
        action = step.get("action", {})
        action_type = action.get("action_type", "")
        if action_type == "mcp":
            count += 1
    return count


def get_all_tags(suite_family: str = "memgui_bench") -> list[str]:
    """Get all unique tags from the registry."""
    registry = get_registry(suite_family)
    tags = set()
    if registry:
        for t_name in registry.list_tasks():
            try:
                t = registry.get_task(t_name)
                if hasattr(t, "task_tags") and t.task_tags:
                    tags.update(t.task_tags)
            except Exception:
                pass
    if suite_family == "memgui_bench":
        tags.update(MEMGUI_DIFFICULTY_TAGS.values())
        return sorted(list(tags), key=_memgui_tag_sort_key)
    return sorted(list(tags))


def _load_memgui_task_list_from_metadata(metadata: dict) -> list[str]:
    task_list = metadata.get("task_list")
    if isinstance(task_list, list) and task_list:
        return [str(task) for task in task_list]

    task_file = metadata.get("task_file")
    difficulty = metadata.get("difficulty")
    if not task_file and not difficulty:
        return []

    try:
        from mobile_world.tasks.memgui_registry import MemGUITaskRegistry

        registry = MemGUITaskRegistry(dataset_path=task_file)
    except Exception as e:
        logger.warning(f"Could not load MemGUI task set from metadata: {e}")
        return []

    tasks = registry.list_tasks()
    difficulties = _normalize_memgui_difficulties(difficulty)
    if difficulties:
        tasks = [
            task_id
            for task_id in tasks
            if registry.get_task(task_id).record.task_difficulty.strip() in difficulties
        ]
    return tasks


def _get_metric_task_set(log_root: str, suite_family: str, task_folders: list[str]) -> list[str]:
    metadata = read_log_metadata(log_root)
    task_list = metadata.get("task_list")
    if isinstance(task_list, list) and task_list:
        return [str(task) for task in task_list]

    if suite_family == "memgui_bench":
        metadata_task_list = _load_memgui_task_list_from_metadata(metadata)
        if metadata_task_list:
            return metadata_task_list

    registry = get_registry(suite_family)
    if registry:
        try:
            return registry.list_tasks()
        except Exception:
            pass
    return task_folders


def get_task_folders(log_root: str) -> list[str]:
    """Get all task folders from log root, excluding backup folders."""
    if not log_root or not os.path.exists(log_root):
        return []

    task_folders = []
    for item in os.listdir(log_root):
        item_path = os.path.join(log_root, item)
        traj_file = os.path.join(item_path, "traj.json")
        if os.path.isdir(item_path) and "_backup_" not in item and os.path.exists(traj_file):
            task_folders.append(item)

    return sorted(task_folders)


def get_task_attempt_folder(log_root: str, task_name: str, attempt: int = 1) -> str:
    """Return the trajectory folder for a task attempt.

    Attempt 1 is the canonical MobileWorld task folder. Additional MemGUI pass@k
    attempts live under `_attempt_trajs/{task_name}/attempt_{n}`.
    """
    if attempt <= 1:
        return os.path.join(log_root, task_name)
    return os.path.join(log_root, "_attempt_trajs", task_name, f"attempt_{attempt}")


def get_task_attempts(log_root: str, task_name: str) -> list[dict]:
    """Return available trajectory attempts for a task."""
    attempts: list[dict] = []
    canonical = get_task_attempt_folder(log_root, task_name, 1)
    if os.path.exists(os.path.join(canonical, "traj.json")):
        attempts.append(
            {
                "attempt": 1,
                "label": "Attempt 1",
                "task_folder": canonical,
                "canonical": True,
            }
        )

    attempt_root = os.path.join(log_root, "_attempt_trajs", task_name)
    if os.path.isdir(attempt_root):
        for item in os.listdir(attempt_root):
            if not item.startswith("attempt_"):
                continue
            try:
                attempt_num = int(item.split("_", 1)[1])
            except (IndexError, ValueError):
                continue
            attempt_folder = os.path.join(attempt_root, item)
            if os.path.exists(os.path.join(attempt_folder, "traj.json")):
                attempts.append(
                    {
                        "attempt": attempt_num,
                        "label": f"Attempt {attempt_num}",
                        "task_folder": attempt_folder,
                        "canonical": False,
                    }
                )

    return sorted(attempts, key=lambda item: item["attempt"])


def is_user_trajectory_log(log_root: str) -> bool:
    """Check if the log root contains user trajectory logs (id_X/user_task/ structure)."""
    if not log_root or not os.path.exists(log_root):
        return False

    for item in os.listdir(log_root):
        item_path = os.path.join(log_root, item)
        if os.path.isdir(item_path) and item.startswith("id_"):
            user_task_path = os.path.join(item_path, "user_task")
            if os.path.isdir(user_task_path):
                return True
    return False


def get_user_trajectory_folders(log_root: str) -> list[str]:
    """Get all user trajectory folders (id_X) from log root."""
    if not log_root or not os.path.exists(log_root):
        return []

    folders = []
    for item in os.listdir(log_root):
        item_path = os.path.join(log_root, item)
        if os.path.isdir(item_path) and item.startswith("id_"):
            user_task_path = os.path.join(item_path, "user_task")
            if os.path.isdir(user_task_path):
                folders.append(item)

    # Sort by numeric id
    def extract_id(name: str) -> int:
        try:
            return int(name.replace("id_", ""))
        except ValueError:
            return 0

    return sorted(folders, key=extract_id)


def get_user_trajectory_task_folder(log_root: str, traj_id: str) -> str:
    """Get the actual task folder for a user trajectory (log_root/id_X/user_task)."""
    return os.path.join(log_root, traj_id, "user_task")


def get_screenshots(task_folder: str) -> list[tuple[int, str, str]]:
    """Get all screenshots from the task folder, sorted by step number.

    Prefers marked screenshots over original screenshots when available.

    Returns:
        List of (step_number, filename, subfolder) tuples sorted by step number.
        subfolder is either "screenshots" or "marked_screenshots".
    """
    screenshots_dir = os.path.join(task_folder, "screenshots")
    marked_dir = os.path.join(task_folder, "marked_screenshots")

    if not os.path.exists(screenshots_dir):
        return []

    screenshots = [f for f in os.listdir(screenshots_dir) if f.endswith(".png")]
    if not screenshots:
        return []

    # Build a set of available marked screenshots
    marked_screenshots: set[str] = set()
    if os.path.exists(marked_dir):
        marked_screenshots = {f for f in os.listdir(marked_dir) if f.endswith(".png")}

    def extract_step_number(filename: str) -> int:
        try:
            # Format: TaskName-0-stepnum.png or marked-TaskName-0-stepnum.png
            parts = filename.rsplit("-", 1)
            if len(parts) == 2:
                return int(parts[1].replace(".png", ""))
        except (ValueError, IndexError):
            pass
        return 0

    result: list[tuple[int, str, str]] = []
    for orig_filename in screenshots:
        step_num = extract_step_number(orig_filename)
        # Check if marked version exists: marked-{original_filename}
        marked_filename = f"marked-{orig_filename}"
        if marked_filename in marked_screenshots:
            result.append((step_num, marked_filename, "marked_screenshots"))
        else:
            result.append((step_num, orig_filename, "screenshots"))

    result.sort(key=lambda x: x[0])
    return result


def get_latest_screenshot(task_folder: str) -> tuple[str, str] | None:
    """Get the latest screenshot filename and subfolder from the task folder.

    Returns:
        Tuple of (filename, subfolder) or None if no screenshots exist.
    """
    screenshots = get_screenshots(task_folder)
    if screenshots:
        return (screenshots[-1][1], screenshots[-1][2])
    return None


def get_all_trajectory_steps(task_folder: str) -> list[dict]:
    """Get all trajectory steps from traj.json."""
    traj_file = os.path.join(task_folder, "traj.json")
    if not os.path.exists(traj_file):
        return []

    try:
        with open(traj_file) as f:
            data = json.load(f)

        # Get the first key (usually "0") and its trajectory
        if data:
            first_key = list(data.keys())[0]
            traj_list = data[first_key].get("traj", [])
            return traj_list
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"Error parsing traj.json in {task_folder}: {e}")

    return []


def get_task_goal(task_folder: str) -> str:
    """Get task goal from traj.json."""
    steps = get_all_trajectory_steps(task_folder)
    if steps and len(steps) > 0:
        # task_goal is the same for all steps, get it from the first one
        return steps[0].get("task_goal", "N/A")
    return "N/A"


def get_task_tools(task_folder: str) -> list[dict]:
    """Get tools from traj.json if available."""
    traj_file = os.path.join(task_folder, "traj.json")
    if not os.path.exists(traj_file):
        return []

    try:
        with open(traj_file) as f:
            data = json.load(f)

        if data:
            first_key = list(data.keys())[0]
            return data[first_key].get("tools", [])
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"Error parsing tools from traj.json in {task_folder}: {e}")

    return []


def get_task_token_usage(task_folder: str) -> dict[str, int] | None:
    """Get token usage from traj.json if available."""
    traj_file = os.path.join(task_folder, "traj.json")
    if not os.path.exists(traj_file):
        return None

    try:
        with open(traj_file) as f:
            data = json.load(f)

        if data:
            # Check top-level token_usage first
            if "token_usage" in data:
                return data["token_usage"]
            # Then check inside first task key
            first_key = list(data.keys())[0]
            return data[first_key].get("token_usage")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"Error parsing token_usage from traj.json in {task_folder}: {e}")

    return None


def get_latest_trajectory_action(task_folder: str) -> dict | None:
    """Get the latest trajectory action from traj.json."""
    steps = get_all_trajectory_steps(task_folder)
    if steps:
        latest = steps[-1]
        return {
            "step": latest.get("step", "N/A"),
            "action_type": latest.get("action", {}).get("action_type", "N/A"),
            "prediction": latest.get("prediction", ""),
        }
    return None


def _task_folder_eval_lookup(task_folder: str) -> tuple[str, str, int | None]:
    normalized = os.path.normpath(task_folder)
    basename = os.path.basename(normalized)
    parent = os.path.dirname(normalized)
    grandparent = os.path.dirname(parent)

    if basename.startswith("attempt_") and os.path.basename(grandparent) == "_attempt_trajs":
        try:
            attempt_num = int(basename.split("_", 1)[1])
        except (IndexError, ValueError):
            attempt_num = None
        return os.path.dirname(grandparent), os.path.basename(parent), attempt_num

    return parent, basename, None


def get_task_status(task_folder: str) -> tuple[str, float | None, str | None]:
    """Get task status: (status, score, reason).

    Status can be:
    - "Finished": has result.txt
    - "Evaluating": trajectory is in MemGUI-Eval and has no evaluator result yet
    - "Running": no result.txt and task activity updated within 10 minutes
    - "Stale": no result.txt and task activity older than 10 minutes
    """
    log_root, task_name, attempt_num = _task_folder_eval_lookup(task_folder)
    evaluating_attempts = get_memgui_evaluating_attempts(
        log_root, task_name=task_name, attempt_num=attempt_num
    )
    if evaluating_attempts:
        attempts = ", ".join(
            f"attempt {item['attempt']}" for item in evaluating_attempts
        )
        return "Evaluating", None, f"MemGUI-Eval in progress for {attempts}"

    result_file = os.path.join(task_folder, "result.txt")
    if os.path.exists(result_file):
        try:
            score, reason = parse_result_file(result_file)
            return "Finished", score, reason
        except Exception as e:
            logger.warning(f"Error parsing result.txt in {task_folder}: {e}")
            return "Finished", None, None

    latest_activity_time = 0.0
    activity_paths = [
        task_folder,
        os.path.join(task_folder, "traj.json"),
        os.path.join(task_folder, "screenshots"),
        os.path.join(task_folder, "marked_screenshots"),
    ]

    for activity_path in activity_paths:
        try:
            if os.path.exists(activity_path):
                latest_activity_time = max(
                    latest_activity_time, os.path.getmtime(activity_path)
                )
        except OSError:
            pass

    # Thread logs are stored under the log root, not in each task folder.
    thread_logs_dir = os.path.join(os.path.dirname(task_folder), "_thread_logs")
    thread_log_prefix = f"{os.path.basename(task_folder)}_"
    if os.path.isdir(thread_logs_dir):
        try:
            for log_file in os.listdir(thread_logs_dir):
                if (
                    not log_file.startswith(thread_log_prefix)
                    or not log_file.endswith(".log")
                ):
                    continue
                log_path = os.path.join(thread_logs_dir, log_file)
                latest_activity_time = max(
                    latest_activity_time, os.path.getmtime(log_path)
                )
        except OSError:
            pass

    if latest_activity_time > 0:
        age_seconds = time.time() - latest_activity_time
        if age_seconds > STALE_TASK_SECONDS:
            return "Stale", None, None
        return "Running", None, None

    return "Stale", None, None


def get_task_info(log_root: str, task_name: str, attempt: int = 1) -> dict | None:
    """Get detailed information for a specific task."""
    task_folder = get_task_attempt_folder(log_root, task_name, attempt)
    if not os.path.exists(task_folder):
        return None

    metadata = read_log_metadata(log_root)
    suite_family = metadata.get("suite_family", "memgui_bench")
    status, score, reason = get_task_status(task_folder)
    screenshots = get_screenshots(task_folder)
    trajectory_steps = get_all_trajectory_steps(task_folder)
    task_goal = get_task_goal(task_folder)
    tools = get_task_tools(task_folder)
    token_usage = get_task_token_usage(task_folder)
    memgui_metadata = (
        get_memgui_task_metadata(task_name) if suite_family == "memgui_bench" else {}
    )
    memgui_eval_info = (
        get_memgui_eval_info(log_root, task_name) if suite_family == "memgui_bench" else {}
    )

    return {
        "name": task_name,
        "attempt": attempt,
        "status": status,
        "score": score,
        "reason": reason,
        "screenshots": screenshots,
        "trajectory_steps": trajectory_steps,
        "task_folder": task_folder,
        "attempts": get_task_attempts(log_root, task_name),
        "task_goal": task_goal,
        "tools": tools,
        "token_usage": token_usage,
        "memgui_metadata": memgui_metadata,
        "memgui_eval_info": memgui_eval_info,
    }


def calculate_task_stats(log_root: str, suite_family: str = "memgui_bench") -> dict:
    """Calculate statistics for all tasks in the log root.

    Metrics:
    - SR (Success Rate): proportion of tasks successfully completed
    - Standard SR: success rate for standard GUI tasks
    - MCP SR: success rate for MCP-augmented tasks
    - User-Interaction SR: success rate for agent-user interaction tasks
    - Ave. Steps: average number of action steps across all trajectories
    - Ave. Queries: average ask_user actions for interaction tasks only
    - Ave. MCP Calls: average MCP tool calls for MCP tasks only
    - UIQ (User Interaction Quality): measures effectiveness and efficiency of ask_user
      UIQ = sum(q_i for i in I_interact) / (|I_interact| + |I_triggered|)
      where q_i = s_i / c_i if c_i > 0 else 0 for interaction tasks,
      and I_triggered = non-interaction tasks that triggered ask_user
    """
    task_folders = get_task_folders(log_root)
    metric_task_set = _get_metric_task_set(log_root, suite_family, task_folders)
    total_task_no = len(metric_task_set)
    if not task_folders:
        memgui_eval_metrics = (
            calculate_memgui_eval_metrics(log_root, total_task_no, metric_task_set)
            if suite_family == "memgui_bench"
            else {}
        )
        return {
            "total_task_no": total_task_no,
            "total": 0,
            "finished": 0,
            "running": 0,
            "evaluating": 0,
            "stale": 0,
            "success": 0,
            "failed": 0,
            "success_rate": 0.0,
            "total_steps": 0,
            "avg_steps": 0.0,
            "mcp_success": 0,
            "mcp_finished": 0,
            "mcp_success_rate": 0.0,
            "user_interaction_success": 0,
            "user_interaction_finished": 0,
            "user_interaction_success_rate": 0.0,
            "standard_success": 0,
            "standard_finished": 0,
            "standard_success_rate": 0.0,
            "uiq": 0.0,
            "avg_queries": 0.0,
            "avg_mcp_calls": 0.0,
            "finished_success_rate": 0.0,
            "memgui_memory_success": 0,
            "memgui_memory_finished": 0,
            "memgui_memory_success_rate": 0.0,
            "memgui_cross_app_success": 0,
            "memgui_cross_app_finished": 0,
            "memgui_cross_app_success_rate": 0.0,
            "memgui_avg_step_ratio": 0.0,
            "memgui_eval": memgui_eval_metrics,
        }

    finished_count = 0
    running_count = 0
    evaluating_count = 0
    stale_count = 0
    success_count = 0
    failed_count = 0
    total_steps = 0

    # Per-tag stats
    mcp_success = 0
    mcp_finished = 0
    user_interaction_success = 0
    user_interaction_finished = 0
    standard_success = 0
    standard_finished = 0

    # UIQ calculation (new formula):
    # UIQ = sum(q_i for i in I_interact) / (|I_interact| + |I_triggered|)
    # where I_triggered = non-interaction tasks that triggered ask_user
    uiq_numerator = 0.0  # sum of q_i for interaction tasks only
    interaction_task_count = 0  # |I_interact|
    triggered_task_count = 0  # |I_triggered| (non-interaction tasks with ask_user)

    # Ave. Queries: sum of ask_user counts for interaction tasks
    total_queries_interaction = 0

    # Ave. MCP Calls: sum of MCP calls for MCP tasks
    total_mcp_calls = 0
    memgui_memory_success = 0
    memgui_memory_finished = 0
    memgui_cross_app_success = 0
    memgui_cross_app_finished = 0
    total_memgui_step_ratio = 0.0
    memgui_step_ratio_count = 0

    for task_name in task_folders:
        task_folder = os.path.join(log_root, task_name)
        status, score, _ = get_task_status(task_folder)
        trajectory_steps = get_all_trajectory_steps(task_folder)
        step_count = len(trajectory_steps)

        # Skip tasks with empty steps for stats too
        if not trajectory_steps:
            continue

        # Get tags for this task
        task_tags = get_task_tags(task_name, suite_family=suite_family)
        has_mcp = "agent-mcp" in task_tags
        has_user_interaction = "agent-user-interaction" in task_tags
        is_standard = not has_mcp and not has_user_interaction
        memgui_metadata = (
            get_memgui_task_metadata(task_name) if suite_family == "memgui_bench" else {}
        )
        is_memgui_memory = bool(memgui_metadata.get("requires_ui_memory"))
        is_memgui_cross_app = bool(memgui_metadata.get("is_cross_app"))
        golden_steps = memgui_metadata.get("golden_steps")
        if isinstance(golden_steps, int) and golden_steps > 0:
            total_memgui_step_ratio += step_count / golden_steps
            memgui_step_ratio_count += 1

        # Count actions
        c_i = count_ask_user_actions(trajectory_steps)
        m_i = count_mcp_actions(trajectory_steps)

        if status == "Finished":
            finished_count += 1
            is_success = score is not None and score > 0.99
            s_i = 1 if is_success else 0

            if is_success:
                success_count += 1
            else:
                failed_count += 1

            # Track per-tag stats
            if has_mcp:
                mcp_finished += 1
                if is_success:
                    mcp_success += 1
                # Ave. MCP Calls: count MCP calls for MCP tasks
                total_mcp_calls += m_i

            if has_user_interaction:
                user_interaction_finished += 1
                if is_success:
                    user_interaction_success += 1
                # Ave. Queries: count ask_user for interaction tasks
                total_queries_interaction += c_i
                # UIQ: calculate q_i for interaction tasks
                interaction_task_count += 1
                if c_i > 0:
                    q_i = s_i / c_i
                else:
                    q_i = 0.0
                uiq_numerator += q_i
            else:
                # Non-interaction task: check if triggered ask_user
                if c_i > 0:
                    triggered_task_count += 1

            if is_standard:
                standard_finished += 1
                if is_success:
                    standard_success += 1

            if suite_family == "memgui_bench":
                if is_memgui_memory:
                    memgui_memory_finished += 1
                    if is_success:
                        memgui_memory_success += 1
                if is_memgui_cross_app:
                    memgui_cross_app_finished += 1
                    if is_success:
                        memgui_cross_app_success += 1

        elif status == "Evaluating":
            evaluating_count += 1
        elif status == "Stale":
            stale_count += 1
        else:
            running_count += 1

        total_steps += step_count

    total = finished_count + running_count + evaluating_count + stale_count
    total_task_no = total_task_no if total_task_no > 0 else total
    success_rate = (success_count / total_task_no * 100) if total_task_no > 0 else 0.0
    finished_success_rate = (
        (success_count / finished_count * 100) if finished_count > 0 else 0.0
    )
    avg_steps = (total_steps / total) if total > 0 else 0.0

    mcp_success_rate = (mcp_success / mcp_finished * 100) if mcp_finished > 0 else 0.0
    user_interaction_success_rate = (
        (user_interaction_success / user_interaction_finished * 100)
        if user_interaction_finished > 0
        else 0.0
    )
    standard_success_rate = (
        (standard_success / standard_finished * 100) if standard_finished > 0 else 0.0
    )

    # UIQ = sum(q_i for i in I_interact) / (|I_interact| + |I_triggered|)
    uiq_denominator = interaction_task_count + triggered_task_count
    uiq = (uiq_numerator / uiq_denominator) if uiq_denominator > 0 else 0.0

    # Ave. Queries = (1/|I_interact|) * sum(c_i for i in I_interact)
    avg_queries = (
        (total_queries_interaction / interaction_task_count) if interaction_task_count > 0 else 0.0
    )

    # Ave. MCP Calls = (1/|I_MCP|) * sum(m_i for i in I_MCP)
    avg_mcp_calls = (total_mcp_calls / mcp_finished) if mcp_finished > 0 else 0.0
    memgui_memory_success_rate = (
        (memgui_memory_success / memgui_memory_finished * 100)
        if memgui_memory_finished > 0
        else 0.0
    )
    memgui_cross_app_success_rate = (
        (memgui_cross_app_success / memgui_cross_app_finished * 100)
        if memgui_cross_app_finished > 0
        else 0.0
    )
    memgui_avg_step_ratio = (
        total_memgui_step_ratio / memgui_step_ratio_count
        if memgui_step_ratio_count > 0
        else 0.0
    )
    memgui_eval_metrics = (
        calculate_memgui_eval_metrics(log_root, total_task_no, metric_task_set)
        if suite_family == "memgui_bench"
        else {}
    )

    return {
        "total_task_no": total_task_no,
        "total": total,
        "finished": finished_count,
        "running": running_count,
        "evaluating": evaluating_count,
        "stale": stale_count,
        "success": success_count,
        "failed": failed_count,
        "success_rate": success_rate,
        "finished_success_rate": finished_success_rate,
        "total_steps": total_steps,
        "avg_steps": avg_steps,
        "mcp_success": mcp_success,
        "mcp_finished": mcp_finished,
        "mcp_success_rate": mcp_success_rate,
        "user_interaction_success": user_interaction_success,
        "user_interaction_finished": user_interaction_finished,
        "user_interaction_success_rate": user_interaction_success_rate,
        "standard_success": standard_success,
        "standard_finished": standard_finished,
        "standard_success_rate": standard_success_rate,
        "uiq": uiq,
        "avg_queries": avg_queries,
        "avg_mcp_calls": avg_mcp_calls,
        "memgui_memory_success": memgui_memory_success,
        "memgui_memory_finished": memgui_memory_finished,
        "memgui_memory_success_rate": memgui_memory_success_rate,
        "memgui_cross_app_success": memgui_cross_app_success,
        "memgui_cross_app_finished": memgui_cross_app_finished,
        "memgui_cross_app_success_rate": memgui_cross_app_success_rate,
        "memgui_avg_step_ratio": memgui_avg_step_ratio,
        "memgui_eval": memgui_eval_metrics,
    }
