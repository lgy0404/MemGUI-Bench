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


def get_log_root_state() -> dict[str, str]:
    """Get the global log root state."""
    return _log_root_state


def read_log_metadata(log_root: str) -> dict:
    """Read metadata.json from a log root directory.

    Returns a dict with at minimum {"suite_family": "memgui_bench"}.
    Falls back to defaults if file doesn't exist (backward compat).
    """
    defaults = {"suite_family": "memgui_bench", "seed": None}
    if not log_root:
        return defaults
    metadata_path = os.path.join(log_root, "metadata.json")
    if not os.path.exists(metadata_path):
        return defaults
    try:
        with open(metadata_path) as f:
            data = json.load(f)
        for key, value in defaults.items():
            data.setdefault(key, value)
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Error reading metadata.json in {log_root}: {e}")
        return defaults


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

    latest_attempt = attempts[-1] if attempts else {}
    max_attempt = max((attempt["attempt"] for attempt in attempts), default=0)
    pass_at = {
        k: any(attempt <= k for attempt in successful_attempts)
        for k in range(1, max(max_attempt, 1) + 1)
    }

    return {
        "attempts": attempts,
        "latest": latest_attempt,
        "successful_attempts": successful_attempts,
        "pass_at": pass_at,
        "max_attempt": max_attempt,
    }


def calculate_memgui_eval_metrics(log_root: str, total_tasks: int) -> dict:
    """Calculate MemGUI leaderboard-style metrics from `_memgui_eval/results.csv`."""
    rows, fieldnames = _read_memgui_results_rows(log_root)
    attempt_prefixes = _get_attempt_prefixes(fieldnames)
    max_attempt = max((attempt for attempt, _ in attempt_prefixes), default=1)

    pass_counts = {k: 0 for k in range(1, max_attempt + 1)}
    pass_memory_counts = {k: 0 for k in range(1, max_attempt + 1)}
    pass_standard_counts = {k: 0 for k in range(1, max_attempt + 1)}
    task_attempt_results: dict[str, dict[int, bool]] = {}

    memory_total = 0
    standard_total = 0
    evaluated_count = 0
    irr_sum = 0.0
    irr_count = 0

    for row in rows:
        task_id = row.get("task_identifier", "")
        if not task_id:
            continue
        is_memory_task = _parse_bool_flag(row.get("requires_ui_memory"))
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
    return sorted(list(tags))


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


def get_task_status(task_folder: str) -> tuple[str, float | None, str | None]:
    """Get task status: (status, score, reason).

    Status can be:
    - "Finished": has result.txt
    - "Running": no result.txt and .log file updated within 10 minutes
    - "Stale": no result.txt and .log file older than 10 minutes
    """
    result_file = os.path.join(task_folder, "result.txt")
    if os.path.exists(result_file):
        try:
            score, reason = parse_result_file(result_file)
            return "Finished", score, reason
        except Exception as e:
            logger.warning(f"Error parsing result.txt in {task_folder}: {e}")
            return "Finished", None, None

    # Check .log file modification time
    log_files = [f for f in os.listdir(task_folder) if f.endswith(".log")]
    if log_files:
        latest_log_time = 0.0
        for log_file in log_files:
            log_path = os.path.join(task_folder, log_file)
            try:
                mtime = os.path.getmtime(log_path)
                latest_log_time = max(latest_log_time, mtime)
            except OSError:
                pass

        if latest_log_time > 0:
            age_seconds = time.time() - latest_log_time
            if age_seconds > 600:  # 10 minutes
                return "Stale", None, None

    return "Running", None, None


def get_task_info(log_root: str, task_name: str) -> dict | None:
    """Get detailed information for a specific task."""
    task_folder = os.path.join(log_root, task_name)
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
        "status": status,
        "score": score,
        "reason": reason,
        "screenshots": screenshots,
        "trajectory_steps": trajectory_steps,
        "task_folder": task_folder,
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
    if not task_folders:
        return {
            "total": 0,
            "finished": 0,
            "running": 0,
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
            "memgui_eval": {},
        }

    finished_count = 0
    running_count = 0
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

        elif status == "Stale":
            stale_count += 1
        else:
            running_count += 1

        total_steps += step_count

    total = finished_count + running_count + stale_count
    registry = get_registry(suite_family)
    total_task_no = len(registry.list_tasks()) if registry else total
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
        calculate_memgui_eval_metrics(log_root, total_task_no)
        if suite_family == "memgui_bench"
        else {}
    )

    return {
        "total_task_no": total_task_no,
        "total": total,
        "finished": finished_count,
        "running": running_count,
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
