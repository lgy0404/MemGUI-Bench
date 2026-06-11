"""Tests for MemGUI-Bench task registry on the MobileWorld runtime."""

import asyncio

from mobile_world.core.cli import create_parser
from mobile_world.core.subcommands import eval as eval_command
from mobile_world.core.subcommands.eval import (
    _normalize_difficulties,
    _resolve_memgui_task_selection,
)
from mobile_world.runtime.utils.models import DEFAULT_IMAGE
from mobile_world.tasks.memgui_registry import MemGUITaskRegistry


def test_memgui_registry_loads_full_task_set():
    registry = MemGUITaskRegistry()

    assert len(registry.tasks) == 128
    task = registry.get_task("001-FindProductAndFilter")
    assert "running shoes for men" in task.goal
    assert "Amazon" in task.app_names
    assert "memgui_bench" in task.task_tags


def test_eval_defaults_to_memgui_suite_and_image():
    parser = create_parser()
    args = parser.parse_args(["eval", "--agent-type", "qwen3vl"])

    assert args.suite_family == "memgui_bench"
    assert args.env_name_prefix == "memgui_bench_env"
    assert args.env_image == DEFAULT_IMAGE
    assert args.step_wait_time is None


def test_memgui_registry_loads_subset_task_file():
    registry = MemGUITaskRegistry("data/memgui-tasks-40.csv")

    assert len(registry.tasks) == 40
    assert registry.list_tasks()[0] == "005-SearchSportsScores"
    assert registry.get_task("005-SearchSportsScores").record.task_difficulty == "1"


def test_eval_parser_accepts_task_file_and_difficulty():
    parser = create_parser()
    args = parser.parse_args(
        [
            "eval",
            "--agent-type",
            "qwen3vl",
            "--task-file",
            "data/memgui-tasks-40.csv",
            "--difficulty",
            "hard",
            "--pass-at-k",
            "3",
        ]
    )

    assert args.task_file == "data/memgui-tasks-40.csv"
    assert args.difficulty == "hard"
    assert args.pass_at_k == 3


def test_memgui_eval_execute_defaults_to_three_second_step_wait(monkeypatch, tmp_path):
    parser = create_parser()
    args = parser.parse_args(
        [
            "eval",
            "--agent-type",
            "qwen3vl",
            "--dry-run",
            "--log-file-root",
            str(tmp_path),
        ]
    )
    captured = {}

    def fake_run_agent_with_evaluation(**kwargs):
        captured.update(kwargs)
        return [], []

    monkeypatch.setattr(eval_command, "run_agent_with_evaluation", fake_run_agent_with_evaluation)

    asyncio.run(eval_command.execute(args))

    assert captured["step_wait_time"] == 3.0


def test_resolve_memgui_task_selection_filters_task_file_by_difficulty():
    tasks, is_task_set_run = _resolve_memgui_task_selection(
        task_arg="ALL",
        task_file="data/memgui-tasks-40.csv",
        difficulty="困难",
    )

    assert is_task_set_run
    assert len(tasks) == 8
    assert "039-TranscribeProductReviews" in tasks
    assert "005-SearchSportsScores" not in tasks


def test_normalize_difficulties_accepts_multiple_aliases():
    assert _normalize_difficulties("easy,中等,3") == {"1", "2", "3"}
