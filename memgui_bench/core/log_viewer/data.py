"""Data loading helpers for MemGUI-Bench trajectory sessions."""

from __future__ import annotations

import ast
import csv
import json
import re
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def read_text(path: Path, limit: int = 20000) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[:limit]


def read_results_rows(log_root: Path) -> list[dict[str, str]]:
    csv_path = log_root / "results.csv"
    if not csv_path.exists():
        return []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def find_session_dirs(path: Path) -> list[Path]:
    if (path / "results.csv").exists():
        return [path]
    if not path.exists():
        return []
    return sorted(child for child in path.iterdir() if child.is_dir() and (child / "results.csv").exists())


def parse_apps(value: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except Exception:
        pass
    return [part.strip() for part in value.split(",") if part.strip()]


def detect_agents(rows: list[dict[str, str]], log_root: Path | None = None) -> list[str]:
    agents: set[str] = set()
    for row in rows:
        for col in row:
            if col.endswith("_successful_attempts"):
                agents.add(col[: -len("_successful_attempts")])
            match = re.match(r"^(.+)_attempt_\d+_completion$", col)
            if match:
                agents.add(match.group(1))
    if log_root and log_root.exists():
        for task_dir in log_root.iterdir():
            if not task_dir.is_dir() or task_dir.name.startswith("."):
                continue
            for agent_dir in task_dir.iterdir():
                if agent_dir.is_dir():
                    agents.add(agent_dir.name)
    return sorted(agents)


def detect_max_attempts(rows: list[dict[str, str]], agents: list[str]) -> int:
    max_attempts = 0
    for row in rows:
        for col in row:
            for agent in agents:
                prefix = f"{agent}_attempt_"
                if col.startswith(prefix) and col.endswith("_completion"):
                    try:
                        attempt = int(col[len(prefix) :].split("_", 1)[0])
                    except ValueError:
                        continue
                    max_attempts = max(max_attempts, attempt)
    return max_attempts or 3


def find_eval_col(row: dict[str, str], agent: str, attempt: int) -> str | None:
    suffix = f"_attempt_{attempt}_evaluation"
    for col in row:
        if col.startswith(f"{agent}_") and col.endswith(suffix):
            return col
    return None


def find_col(row: dict[str, str], agent: str, attempt: int, metric: str) -> str | None:
    exact = f"{agent}_attempt_{attempt}_{metric}"
    if exact in row:
        return exact
    suffix = f"_attempt_{attempt}_{metric}"
    for col in row:
        if col.startswith(f"{agent}_") and col.endswith(suffix):
            return col
    return None


def attempt_dir(log_root: Path, task_id: str, agent: str, attempt: int) -> Path:
    return log_root / task_id / agent / f"attempt_{attempt}"


def attempt_status(row: dict[str, str], log_root: Path, agent: str, attempt: int) -> dict[str, Any]:
    task_id = row.get("task_identifier", "")
    directory = attempt_dir(log_root, task_id, agent, attempt)
    completion = row.get(f"{agent}_attempt_{attempt}_completion", "")
    eval_col = find_eval_col(row, agent, attempt)
    evaluation = row.get(eval_col, "") if eval_col else ""

    status = "pending"
    if evaluation == "S":
        status = "success"
    elif evaluation == "F":
        status = "failure"
    elif evaluation == "E":
        status = "error"
    elif completion == "Y" or (directory / "log.json").exists():
        status = "executed"
    elif (directory / "error.json").exists():
        status = "error"

    def value(metric: str, default: str = "") -> str:
        col = find_col(row, agent, attempt, metric)
        return row.get(col, default) if col else default

    eval_summary = read_json(directory / "evaluation_summary.json", {}) or {}
    final_decision = read_json(directory / "final_decision.json", {}) or {}
    reason = eval_summary.get("reason") or final_decision.get("reason") or ""

    return {
        "agent": agent,
        "attempt": attempt,
        "status": status,
        "completion": completion,
        "evaluation": evaluation,
        "steps": value("total_steps", "0"),
        "time": value("total_time", "0"),
        "cost": value("total_token_cost", "0"),
        "failure_step": value("failure_step", ""),
        "reason": reason,
        "path": directory,
        "has_log": (directory / "log.json").exists(),
    }


def load_session(log_root: Path) -> dict[str, Any]:
    log_root = log_root.resolve()
    rows = read_results_rows(log_root)
    agents = detect_agents(rows, log_root)
    max_attempts = detect_max_attempts(rows, agents)
    metrics = read_json(log_root / "metrics_summary.json", {}) or {}

    tasks = []
    for row in rows:
        task_id = row.get("task_identifier", "")
        attempts = {
            agent: [attempt_status(row, log_root, agent, attempt) for attempt in range(1, max_attempts + 1)]
            for agent in agents
        }
        best_status = "pending"
        if any(item["status"] == "success" for values in attempts.values() for item in values):
            best_status = "success"
        elif any(item["status"] == "failure" for values in attempts.values() for item in values):
            best_status = "failure"
        elif any(item["status"] == "executed" for values in attempts.values() for item in values):
            best_status = "executed"
        elif any(item["status"] == "error" for values in attempts.values() for item in values):
            best_status = "error"

        tasks.append(
            {
                "id": task_id,
                "description": row.get("task_description", ""),
                "apps": parse_apps(row.get("task_app", "")),
                "memory": str(row.get("requires_ui_memory", "")).strip().upper() == "Y",
                "difficulty": row.get("task_difficulty", ""),
                "golden_steps": row.get("golden_steps", ""),
                "category": row.get("category", ""),
                "best_status": best_status,
                "attempts": attempts,
                "row": row,
            }
        )

    return {
        "root": log_root,
        "name": log_root.name,
        "rows": rows,
        "agents": agents,
        "max_attempts": max_attempts,
        "metrics": metrics,
        "tasks": tasks,
    }


def calculate_stats(log_root: Path) -> dict[str, Any]:
    session = load_session(log_root)
    tasks = session["tasks"]
    total = len(tasks)
    success = sum(1 for task in tasks if task["best_status"] == "success")
    failure = sum(1 for task in tasks if task["best_status"] == "failure")
    executed = sum(1 for task in tasks if task["best_status"] in {"success", "failure", "executed", "error"})
    memory_total = sum(1 for task in tasks if task["memory"])
    memory_success = sum(1 for task in tasks if task["memory"] and task["best_status"] == "success")

    steps = []
    for task in tasks:
        for attempts in task["attempts"].values():
            for attempt in attempts:
                try:
                    value = float(attempt["steps"])
                except (TypeError, ValueError):
                    value = 0
                if value:
                    steps.append(value)

    return {
        "name": session["name"],
        "total": total,
        "executed": executed,
        "success": success,
        "failure": failure,
        "success_rate": (success / total * 100) if total else 0.0,
        "memory_total": memory_total,
        "memory_success": memory_success,
        "memory_success_rate": (memory_success / memory_total * 100) if memory_total else 0.0,
        "avg_steps": (sum(steps) / len(steps)) if steps else 0.0,
        "agents": session["agents"],
    }


def _step_number_from_name(path: Path) -> int:
    match = re.search(r"(\d+)", path.stem)
    if not match:
        return 0
    return int(match.group(1))


def rel_to_root(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def load_task_detail(log_root: Path, task_id: str, agent: str, attempt: int) -> dict[str, Any]:
    session = load_session(log_root)
    task = next((item for item in session["tasks"] if item["id"] == task_id), None)
    directory = attempt_dir(log_root, task_id, agent, attempt)
    log_data = read_json(directory / "log.json", []) or []
    step_logs = [item for item in log_data if isinstance(item, dict) and "step" in item]
    summary = next((item for item in reversed(log_data) if isinstance(item, dict) and "total_steps" in item), {})

    eval_summary = read_json(directory / "evaluation_summary.json", {}) or {}
    final_decision = read_json(directory / "final_decision.json", {}) or {}
    irr = read_json(directory / "irr_analysis.json", {}) or final_decision.get("irr_analysis", {})
    badcase = read_json(directory / "badcase_analysis.json", {}) or final_decision.get("badcase_analysis", {})
    error = read_json(directory / "error.json", {}) or {}

    descriptions = eval_summary.get("step_by_step_analysis") or eval_summary.get("step_descriptions") or {}
    if not isinstance(descriptions, dict):
        descriptions = {}

    screenshots = sorted(
        [path for path in directory.glob("*.png") if path.stem.isdigit()],
        key=lambda p: int(p.stem),
    )
    single_actions = sorted((directory / "single_actions").glob("step_*.png"), key=_step_number_from_name)
    visual_actions = sorted((directory / "visualize_actions").glob("step_*.png"), key=_step_number_from_name)
    puzzles = sorted((directory / "puzzle").glob("*.png"))

    files = {
        "stdout": read_text(directory / "stdout.txt"),
        "stderr": read_text(directory / "stderr.txt"),
        "detailed_model_logs": read_json(directory / "detailed_model_logs.json", []),
    }

    return {
        "session": session,
        "task": task,
        "agent": agent,
        "attempt": attempt,
        "directory": directory,
        "log_data": log_data,
        "step_logs": step_logs,
        "summary": summary,
        "evaluation_summary": eval_summary,
        "final_decision": final_decision,
        "irr": irr,
        "badcase": badcase,
        "error": error,
        "descriptions": descriptions,
        "screenshots": screenshots,
        "single_actions": single_actions,
        "visual_actions": visual_actions,
        "puzzles": puzzles,
        "files": files,
    }
