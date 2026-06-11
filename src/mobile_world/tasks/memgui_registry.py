"""Registry for MemGUI-Bench CSV tasks."""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path

from mobile_world.tasks.memgui_task import MemGUITask, MemGUITaskRecord

DEFAULT_DATASET = "data/memgui-tasks-all.csv"
logger = logging.getLogger(__name__)


def _candidate_dataset_paths(dataset_path: str | None = None) -> list[Path]:
    raw_path = dataset_path or os.getenv("MEMGUI_DATASET_PATH") or DEFAULT_DATASET
    path = Path(raw_path).expanduser()
    candidates = [path] if path.is_absolute() else [Path.cwd() / path]

    current = Path(__file__).resolve()
    for parent in current.parents:
        candidates.append(parent / raw_path)
        candidates.append(parent / DEFAULT_DATASET)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            deduped.append(resolved)
            seen.add(resolved)
    return deduped


def resolve_dataset_path(dataset_path: str | None = None) -> Path:
    for candidate in _candidate_dataset_paths(dataset_path):
        if candidate.exists():
            return candidate
    checked = "\n".join(str(path) for path in _candidate_dataset_paths(dataset_path))
    raise FileNotFoundError(f"MemGUI dataset not found. Checked:\n{checked}")


class MemGUITaskRegistry:
    """Loads MemGUI-Bench tasks from the benchmark CSV.

    The interface intentionally matches MobileWorld's TaskRegistry and
    AndroidWorld's AWTaskRegistry so the server can switch suite families
    without changing its routing or action execution logic.
    """

    def __init__(self, dataset_path: str | None = None):
        self.dataset_path = resolve_dataset_path(dataset_path)
        self.tasks: dict[str, MemGUITask] = {}
        self._load_tasks()

    def _load_tasks(self) -> None:
        logger.info(f"Loading MemGUI-Bench tasks from {self.dataset_path}")
        with self.dataset_path.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                record = MemGUITaskRecord.from_row(row)
                if not record.task_identifier:
                    continue
                self.tasks[record.task_identifier] = MemGUITask(record)
        logger.info(f"Loaded {len(self.tasks)} MemGUI-Bench tasks")

    def get_task(self, task_name: str) -> MemGUITask:
        if task_name not in self.tasks:
            logger.error(
                f"Task '{task_name}' not found. Available tasks: {list(self.tasks.keys())}"
            )
            raise KeyError(f"Task '{task_name}' not found in MemGUI-Bench registry")
        return self.tasks[task_name]

    def list_tasks(self) -> list[str]:
        return list(self.tasks.keys())

    def has_task(self, task_name: str) -> bool:
        return task_name in self.tasks
