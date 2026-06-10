"""Tests for MemGUI-Bench task registry on the MobileWorld runtime."""

from mobile_world.core.cli import create_parser
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
    assert "memgui/memgui-bench:26020301" in args.env_image
