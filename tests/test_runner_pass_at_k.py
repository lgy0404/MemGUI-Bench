"""Tests for MemGUI pass@k runner semantics."""

import csv
import json
from queue import Queue
from types import SimpleNamespace

import pytest

from mobile_world.core import runner


def test_pass_at_k_stops_after_first_success(monkeypatch, tmp_path):
    executed_attempts = []

    monkeypatch.setattr(runner, "_resolve_task_max_step", lambda *args, **kwargs: 5)
    monkeypatch.setattr(runner, "create_agent", lambda *args, **kwargs: object())

    def fake_execute_single_task(*args, **kwargs):
        attempt_num = kwargs["attempt_num"]
        executed_attempts.append(attempt_num)
        score = 1.0 if attempt_num == 2 else 0.0
        return attempt_num, score, f"attempt {attempt_num}"

    monkeypatch.setattr(runner, "_execute_single_task", fake_execute_single_task)

    env = SimpleNamespace(base_url="http://env-0")
    env_queue = Queue()
    env_queue.put((env, "container-0"))

    result = runner._process_task_on_env(
        task_name="001-FindProductAndFilter",
        env_queue=env_queue,
        agent_type="qwen3vl",
        model_name="model",
        llm_base_url="http://llm",
        api_key="key",
        log_file_root=str(tmp_path),
        max_step=None,
        suite_family="memgui_bench",
        pass_at_k=3,
    )

    assert executed_attempts == [1, 2]
    assert result["score"] == 1.0
    assert [item["attempt"] for item in result["attempts"]] == [1, 2]

    result_text = (tmp_path / "001-FindProductAndFilter" / "result.txt").read_text()
    assert "pass@3: success at attempt 2" in result_text
    assert "attempts_run=2/3" in result_text


def test_pass_at_k_finished_scan_allows_old_pass1_failure(tmp_path):
    for task_name, result_text in {
        "task-pass1-failed": "score: 0.0\nreason: pass@1 failure",
        "task-pass1-success": "score: 1.0\nreason: pass@1 success",
        "task-pass3-failed": "score: 0.0\nreason: pass@3: all 3 attempts failed",
    }.items():
        task_dir = tmp_path / task_name
        task_dir.mkdir()
        (task_dir / "result.txt").write_text(result_text)

    finished, scores = runner._scan_finished_memgui_pass_at_k_tasks(
        str(tmp_path),
        ["task-pass1-failed", "task-pass1-success", "task-pass3-failed"],
        pass_at_k=3,
    )

    assert finished == ["task-pass1-success", "task-pass3-failed"]
    assert scores == [1.0, 0.0]


def test_memgui_finished_scan_retries_eval_error_without_csv_decision(tmp_path):
    result_text_by_task = {
        "task-normal-failed": "score: 0.0\nreason: task failed",
        "task-eval-error": (
            "score: 0.0\n"
            "reason: MemGUI-Eval error: libGL.so.1: cannot open shared object file"
        ),
        "task-eval-error-with-csv": (
            "score: 0.0\n"
            "reason: MemGUI-Eval error: visualization_error"
        ),
    }
    for task_name, result_text in result_text_by_task.items():
        task_dir = tmp_path / task_name
        task_dir.mkdir()
        (task_dir / "result.txt").write_text(result_text)

    eval_root = tmp_path / "_memgui_eval"
    eval_root.mkdir()
    with (eval_root / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["task_identifier", "qwen3vl_attempt_1_evaluation"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "task_identifier": "task-eval-error-with-csv",
                "qwen3vl_attempt_1_evaluation": "E",
            }
        )

    finished, scores = runner._scan_finished_memgui_pass_at_k_tasks(
        str(tmp_path),
        list(result_text_by_task),
        pass_at_k=1,
    )

    assert finished == ["task-normal-failed", "task-eval-error-with-csv"]
    assert scores == [0.0, 0.0]


def test_runner_writes_selected_task_set_metadata(tmp_path):
    tasks = ["005-SearchSportsScores", "006-SearchSportsScores"]

    results, no_results = runner.run_agent_with_evaluation(
        agent_type="qwen3vl",
        model_name="model",
        llm_base_url="http://llm",
        log_file_root=str(tmp_path),
        tasks=tasks,
        max_step=None,
        aw_urls=[],
        api_key="key",
        dry_run=True,
        suite_family="memgui_bench",
        pass_at_k=3,
        task_file="data/memgui-tasks-40.csv",
        difficulty="easy",
        step_wait_time=3.0,
    )

    assert results == []
    assert no_results == []

    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["task_list"] == tasks
    assert metadata["task_count"] == 2
    assert metadata["task_file"] == "data/memgui-tasks-40.csv"
    assert metadata["difficulty"] == "easy"
    assert metadata["pass_at_k"] == 3


def test_runner_marks_metadata_failed_when_run_errors(monkeypatch, tmp_path):
    tasks = ["005-SearchSportsScores"]

    def fail_scan(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "_scan_finished_memgui_pass_at_k_tasks", fail_scan)

    with pytest.raises(RuntimeError, match="boom"):
        runner.run_agent_with_evaluation(
            agent_type="qwen3vl",
            model_name="model",
            llm_base_url="http://llm",
            log_file_root=str(tmp_path),
            tasks=tasks,
            max_step=None,
            aw_urls=[],
            api_key="key",
            dry_run=True,
            suite_family="memgui_bench",
            pass_at_k=1,
        )

    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["run_status"] == "failed"
    assert metadata["run_error_type"] == "RuntimeError"
    assert metadata["run_error"] == "boom"
