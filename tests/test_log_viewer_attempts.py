"""Tests for viewing MemGUI pass@k attempts."""

import csv
import json
import os
import time

from mobile_world.core.log_viewer.utils import (
    STALE_TASK_SECONDS,
    calculate_task_stats,
    get_all_tags,
    get_memgui_attempt_statuses,
    get_memgui_eval_info,
    get_task_attempts,
    get_task_filter_tags,
    get_task_info,
    get_task_status,
)
from mobile_world.core.subcommands.logs import print_results_table


def _write_traj(task_dir, task_name: str, text: str) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "traj.json").write_text(
        json.dumps(
            {
                "0": {
                    "traj": [
                        {
                            "step": 1,
                            "task_goal": f"Goal for {task_name}",
                            "prediction": text,
                            "action": {"action_type": "input_text", "text": text},
                        }
                    ]
                }
            }
        )
    )
    (task_dir / "result.txt").write_text(f"score: 1.0\nreason: {text}")


def test_log_viewer_discovers_and_reads_pass_at_k_attempts(tmp_path):
    task_name = "001-FindProductAndFilter"
    _write_traj(tmp_path / task_name, task_name, "attempt-one")
    _write_traj(tmp_path / "_attempt_trajs" / task_name / "attempt_2", task_name, "attempt-two")

    attempts = get_task_attempts(str(tmp_path), task_name)
    assert [item["attempt"] for item in attempts] == [1, 2]

    attempt_two_info = get_task_info(str(tmp_path), task_name, attempt=2)
    assert attempt_two_info is not None
    assert attempt_two_info["attempt"] == 2
    assert attempt_two_info["task_folder"].endswith("_attempt_trajs/001-FindProductAndFilter/attempt_2")
    assert attempt_two_info["trajectory_steps"][0]["prediction"] == "attempt-two"


def test_memgui_stats_use_selected_task_set_denominator(tmp_path):
    task_names = ["005-SearchSportsScores", "006-SearchSportsScores"]
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "suite_family": "memgui_bench",
                "pass_at_k": 3,
                "task_list": task_names,
                "task_count": len(task_names),
            }
        )
    )
    _write_traj(tmp_path / task_names[0], task_names[0], "success")

    eval_root = tmp_path / "_memgui_eval"
    eval_root.mkdir()
    with (eval_root / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "task_identifier",
                "requires_ui_memory",
                "qwen3vl_attempt_1_evaluation",
                "qwen3vl_attempt_1_details",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "task_identifier": task_names[0],
                "requires_ui_memory": "N",
                "qwen3vl_attempt_1_evaluation": "S",
                "qwen3vl_attempt_1_details": "success",
            }
        )

    stats = calculate_task_stats(str(tmp_path), suite_family="memgui_bench")

    assert stats["total_task_no"] == 2
    assert stats["success_rate"] == 50.0
    assert stats["memgui_eval"]["max_attempt"] == 3
    assert stats["memgui_eval"]["pass_counts"][1] == 1
    assert stats["memgui_eval"]["pass_rates"][1] == 50.0
    assert stats["memgui_eval"]["pass_rates"][3] == 50.0


def test_logs_results_prints_memgui_metrics(tmp_path, capsys, monkeypatch):
    import rich.console

    class WideConsole(rich.console.Console):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, width=220, color_system=None, **kwargs)

    monkeypatch.setattr(rich.console, "Console", WideConsole)

    task_names = ["005-SearchSportsScores", "006-SearchSportsScores"]
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "suite_family": "memgui_bench",
                "pass_at_k": 3,
                "task_list": task_names,
                "task_count": len(task_names),
            }
        )
    )

    eval_root = tmp_path / "_memgui_eval"
    eval_root.mkdir()
    with (eval_root / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "task_identifier",
                "requires_ui_memory",
                "qwen3vl_attempt_1_evaluation",
                "qwen3vl_attempt_2_evaluation",
                "qwen3vl_attempt_1_irr_percentage",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "task_identifier": task_names[0],
                "requires_ui_memory": "N",
                "qwen3vl_attempt_1_evaluation": "S",
                "qwen3vl_attempt_2_evaluation": "",
                "qwen3vl_attempt_1_irr_percentage": "",
            }
        )
        writer.writerow(
            {
                "task_identifier": task_names[1],
                "requires_ui_memory": "Y",
                "qwen3vl_attempt_1_evaluation": "F",
                "qwen3vl_attempt_2_evaluation": "S",
                "qwen3vl_attempt_1_irr_percentage": "50",
            }
        )

    print_results_table([str(tmp_path)])
    output = capsys.readouterr().out

    assert "MemGUI Results Summary" in output
    assert "P@1%" in output
    assert "P@2%" in output
    assert "P@3%" in output
    assert "Task Set" in output
    assert "Logged" in output
    assert "Evaluated" in output
    assert "Evaluating" in output
    assert "IRR%" in output
    assert "MTPR" in output
    assert "FRR%" in output
    assert "MCP SR%" not in output


def test_memgui_status_counts_evaluating_attempt(tmp_path):
    task_name = "005-SearchSportsScores"
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "suite_family": "memgui_bench",
                "pass_at_k": 1,
                "task_list": [task_name],
                "task_count": 1,
            }
        )
    )

    task_dir = tmp_path / task_name
    task_dir.mkdir()
    (task_dir / "traj.json").write_text(
        json.dumps(
            {
                "0": {
                    "traj": [
                        {
                            "step": 1,
                            "task_goal": f"Goal for {task_name}",
                            "prediction": "done with execution",
                            "action": {"action_type": "wait"},
                        }
                    ]
                }
            }
        )
    )

    eval_root = tmp_path / "_memgui_eval"
    eval_root.mkdir()
    with (eval_root / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "task_identifier",
                "requires_ui_memory",
                "qwen3vl_attempt_1_evaluation",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "task_identifier": task_name,
                "requires_ui_memory": "N",
                "qwen3vl_attempt_1_evaluation": "",
            }
        )
    workspace = eval_root / task_name / "qwen3vl" / "attempt_1"
    workspace.mkdir(parents=True)
    (workspace / "log.json").write_text("[]")

    status, score, reason = get_task_status(str(task_dir))
    stats = calculate_task_stats(str(tmp_path), suite_family="memgui_bench")

    assert status == "Evaluating"
    assert score is None
    assert "MemGUI-Eval in progress" in reason
    assert stats["evaluating"] == 1
    assert stats["running"] == 0
    assert stats["finished"] == 0
    assert stats["memgui_eval"]["max_attempt"] == 1

    memgui_eval_info = get_memgui_eval_info(str(tmp_path), task_name)
    attempt_statuses = get_memgui_attempt_statuses(memgui_eval_info)
    assert attempt_statuses[0]["label"] == "Evaluating"


def test_memgui_filter_tags_include_difficulty_and_categories_last():
    tags = get_all_tags("memgui_bench")

    assert "Difficulty: Easy" in tags
    assert "Difficulty: Medium" in tags
    assert "Difficulty: Hard" in tags
    assert "E-commerce: Product Search" in tags
    assert tags.index("Difficulty: Easy") < tags.index("memgui_bench")
    assert tags.index("memgui_bench") < tags.index("E-commerce: Product Search")

    task_tags = get_task_filter_tags("005-SearchSportsScores", "memgui_bench")
    assert "Difficulty: Easy" in task_tags


def test_unfinished_task_without_result_becomes_stale(tmp_path):
    task_name = "001-FindProductAndFilter"
    task_dir = tmp_path / task_name
    screenshots_dir = task_dir / "screenshots"
    screenshots_dir.mkdir(parents=True)
    (task_dir / "traj.json").write_text(json.dumps({"0": {"traj": [{"step": 1}]}}))
    (screenshots_dir / f"{task_name}-0-1.png").write_bytes(b"fake")

    old_time = time.time() - STALE_TASK_SECONDS - 5
    for path in [task_dir, task_dir / "traj.json", screenshots_dir]:
        os.utime(path, (old_time, old_time))

    status, score, reason = get_task_status(str(task_dir))

    assert status == "Stale"
    assert score is None
    assert reason is None
