"""MemGUI-Bench task wrapper for the MobileWorld runtime."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import Any


def _parse_list_cell(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return [value]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return [str(parsed)]


@dataclass(frozen=True)
class MemGUITaskRecord:
    task_identifier: str
    task_description: str
    task_app: str
    num_apps: str
    is_cross_app: str
    category: str
    requires_ui_memory: str
    shortcut_potential: str
    output_type: str
    golden_steps: str
    task_difficulty: str
    task_language: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "MemGUITaskRecord":
        values = {field: str(row.get(field, "") or "") for field in cls.__dataclass_fields__}
        return cls(**values)


class MemGUITask:
    """A MemGUI task exposed through MobileWorld's BaseTask protocol.

    MemGUI-Bench evaluates final task completion from the saved trajectory with
    MemGUI-Eval. The server-side task object therefore owns task metadata and
    initialization only; scoring is attached by the runner after TrajLogger has
    written MobileWorld-format logs.
    """

    start_on_home_screen = True

    def __init__(self, record: MemGUITaskRecord):
        self.record = record
        self.initialized = False

    @property
    def name(self) -> str:
        return self.record.task_identifier

    @property
    def app_names(self) -> set[str]:
        return set(_parse_list_cell(self.record.task_app))

    @property
    def goal(self) -> str:
        return self.record.task_description

    @property
    def snapshot_tag(self) -> str | None:
        tag = os.getenv("MEMGUI_SNAPSHOT_TAG", "").strip()
        if tag.lower() in {"", "none", "false", "0"}:
            return None
        return tag

    @property
    def task_tags(self) -> set[str]:
        tags = {"memgui_bench"}
        tags.update(_parse_list_cell(self.record.category))
        if self.record.requires_ui_memory.upper() == "Y":
            tags.add("memory-intensive")
        if self.record.is_cross_app.upper() == "Y":
            tags.add("cross-app")
        return tags

    @property
    def complexity(self) -> float:
        try:
            return float(self.record.task_difficulty)
        except ValueError:
            return 0.0

    def initialize_task(self, controller: Any) -> bool | None:
        if self.snapshot_tag is not None:
            if not controller.load_snapshot(self.snapshot_tag):
                return False
            controller.app_switch()

        if self.start_on_home_screen:
            controller.home()

        controller.interaction_cache = ""
        controller.user_agent_chat_history = []
        self.initialized = True
        return True

    def is_successful(self, controller: Any) -> tuple[float, str]:
        if not self.initialized:
            raise RuntimeError(f"{self.name}.initialize_task() must be called first.")
        return (
            0.0,
            "MemGUI-Bench success is evaluated from MobileWorld trajectory logs by MemGUI-Eval.",
        )

    def tear_down(self, controller: Any) -> bool:
        controller.interaction_cache = ""
        controller.user_agent_chat_history = []
        self.initialized = False
        return True
