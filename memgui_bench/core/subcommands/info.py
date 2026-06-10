"""Info subcommands for MemGUI-Bench."""

from __future__ import annotations

import argparse
import ast
import csv
import sys
from collections import Counter
from pathlib import Path

from memgui_bench.core.paths import project_root


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("info", help="Display tasks, agents, and app statistics")
    info_subparsers = parser.add_subparsers(dest="info_command", help="Info commands")

    task = info_subparsers.add_parser("task", help="Display task information")
    task.add_argument("--name", help="Show one task by task_identifier.")
    task.add_argument("--filter", help="Case-insensitive filter over id, app, category, description.")
    task.add_argument("--limit", type=int, default=30, help="Maximum rows to print.")
    task.add_argument("--dataset", help="Dataset CSV path. Defaults to config DATASET_PATH.")
    task.add_argument("--export-excel", "--export_excel", dest="export_excel", help="Export to Excel.")

    agent = info_subparsers.add_parser("agent", help="Display configured agents")
    agent.add_argument("--filter", help="Case-insensitive filter over agent name.")

    app = info_subparsers.add_parser("app", help="Display app task counts")
    app.add_argument("--filter", help="Case-insensitive filter over app name.")
    app.add_argument("--dataset", help="Dataset CSV path. Defaults to config DATASET_PATH.")


def _load_config() -> dict:
    root = project_root()
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from config_loader import load_config

        config_path = root / "config.yaml"
        if config_path.exists():
            return load_config(str(config_path), verbose=False)
    except Exception:
        pass

    try:
        import yaml

        with open(root / "config.yaml.example.opensource", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _dataset_path(dataset_arg: str | None = None) -> Path:
    root = project_root()
    config = _load_config()
    raw_path = dataset_arg or config.get("DATASET_PATH") or "./data/memgui-tasks-all.csv"
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _read_tasks(dataset_arg: str | None = None) -> list[dict[str, str]]:
    path = _dataset_path(dataset_arg)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _parse_apps(value: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except Exception:
        pass
    return [part.strip() for part in value.split(",") if part.strip()]


def _matches(row: dict[str, str], needle: str | None) -> bool:
    if not needle:
        return True
    needle = needle.lower()
    haystack = " ".join(str(value) for value in row.values()).lower()
    return needle in haystack


def _print_rows(rows: list[list[str]], headers: list[str]) -> None:
    if not rows:
        print("No rows.")
        return
    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = min(max(widths[idx], len(cell)), 64)

    def trim(value: str, width: int) -> str:
        if len(value) <= width:
            return value
        return value[: max(width - 3, 0)] + "..."

    header = "  ".join(trim(headers[idx], widths[idx]).ljust(widths[idx]) for idx in range(len(headers)))
    print(header)
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(trim(row[idx], widths[idx]).ljust(widths[idx]) for idx in range(len(headers))))


def _execute_task(args: argparse.Namespace) -> int:
    try:
        tasks = _read_tasks(args.dataset)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    if args.name:
        tasks = [row for row in tasks if row.get("task_identifier") == args.name]
    else:
        tasks = [row for row in tasks if _matches(row, args.filter)]

    if args.export_excel:
        return _export_tasks(tasks, args.export_excel)

    total = len(tasks)
    rows = []
    for row in tasks[: args.limit]:
        rows.append(
            [
                row.get("task_identifier", ""),
                ", ".join(_parse_apps(row.get("task_app", ""))),
                row.get("requires_ui_memory", ""),
                row.get("task_difficulty", ""),
                row.get("golden_steps", ""),
                row.get("task_description", ""),
            ]
        )
    _print_rows(rows, ["Task", "Apps", "Memory", "Diff", "Steps", "Description"])
    if total > len(rows):
        print(f"... {total - len(rows)} more. Use --limit to show more.")
    print(f"Total tasks: {total}")
    return 0


def _export_tasks(tasks: list[dict[str, str]], output: str) -> int:
    try:
        import pandas as pd
    except Exception as exc:
        print(f"Error: pandas/openpyxl is required for Excel export: {exc}")
        return 1

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(tasks).to_excel(out, index=False)
    print(f"Exported {len(tasks)} tasks to {out}")
    return 0


def _execute_agent(args: argparse.Namespace) -> int:
    config = _load_config()
    agents = config.get("AGENTS", [])
    rows = []
    for agent in agents:
        name = str(agent.get("NAME", ""))
        if args.filter and args.filter.lower() not in name.lower():
            continue
        rows.append([name, str(agent.get("ENV_NAME", "")), str(agent.get("REPO_PATH", ""))])
    _print_rows(rows, ["Agent", "Env", "Repo Path"])
    print(f"Total agents: {len(rows)}")
    return 0


def _execute_app(args: argparse.Namespace) -> int:
    try:
        tasks = _read_tasks(args.dataset)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    counts: Counter[str] = Counter()
    memory_counts: Counter[str] = Counter()
    for row in tasks:
        apps = _parse_apps(row.get("task_app", ""))
        for app in apps:
            counts[app] += 1
            if str(row.get("requires_ui_memory", "")).strip().upper() == "Y":
                memory_counts[app] += 1

    rows = []
    for app, count in counts.most_common():
        if args.filter and args.filter.lower() not in app.lower():
            continue
        rows.append([app, str(count), str(memory_counts[app])])
    _print_rows(rows, ["App", "Tasks", "Memory Tasks"])
    print(f"Total apps: {len(rows)}")
    return 0


def execute(args: argparse.Namespace) -> int:
    if args.info_command == "task":
        return _execute_task(args)
    if args.info_command == "agent":
        return _execute_agent(args)
    if args.info_command == "app":
        return _execute_app(args)
    print("Error: please specify an info subcommand (task, agent, app).")
    return 1

