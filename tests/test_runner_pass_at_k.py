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


def _write_request_logs(root, task_name, attempt_nums, agent_type="memgui"):
    for attempt_num in attempt_nums:
        if attempt_num == 1:
            traj_dir = root / task_name
        else:
            traj_dir = root / "_attempt_trajs" / task_name / f"attempt_{attempt_num}"
        traj_dir.mkdir(parents=True, exist_ok=True)
        (traj_dir / "traj.json").write_text('{"0": {"traj": []}}')
        request_dir = traj_dir / "agent_llm_requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        (request_dir / "request_000001_attempt_01.json").write_text("{}")

        eval_dir = (
            root
            / "_memgui_eval"
            / task_name
            / agent_type
            / f"attempt_{attempt_num}"
            / "eval_llm_requests"
        )
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "0001_final_decision_phase1.json").write_text("{}")


def _write_attempt_evaluations(root, task_name, evaluations):
    eval_root = root / "_memgui_eval"
    eval_root.mkdir(exist_ok=True)
    fieldnames = ["task_identifier"] + [
        f"memgui_attempt_{attempt_num}_evaluation"
        for attempt_num in sorted(evaluations)
    ]
    with (eval_root / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "task_identifier": task_name,
                **{
                    f"memgui_attempt_{attempt_num}_evaluation": evaluation
                    for attempt_num, evaluation in evaluations.items()
                },
            }
        )


def test_memgui_finished_scan_reruns_old_results_without_request_logs(tmp_path):
    task_name = "074-TranslateAndSendMessage"
    task_dir = tmp_path / task_name
    task_dir.mkdir()
    (task_dir / "traj.json").write_text("{}")
    (task_dir / "result.txt").write_text(
        "score: 0.0\n"
        "reason: pass@3: all 3 attempts failed; latest_reason=Task execution failed "
        "at attempt 3: RuntimeError: Failed to initialize task "
        "074-TranslateAndSendMessage: 503 Server Error: Service Unavailable"
    )

    finished, scores = runner._scan_finished_memgui_pass_at_k_tasks(
        str(tmp_path),
        [task_name],
        pass_at_k=3,
        agent_type="memgui",
        require_request_logs=True,
    )

    assert finished == []
    assert scores == []


def test_memgui_finished_scan_keeps_completed_tasks_with_request_logs(tmp_path):
    task_name = "task-pass3-failed"
    task_dir = tmp_path / task_name
    task_dir.mkdir()
    (task_dir / "result.txt").write_text(
        "score: 0.0\nreason: pass@3: all 3 attempts failed"
    )
    _write_request_logs(tmp_path, task_name, [1, 2, 3])
    _write_attempt_evaluations(tmp_path, task_name, {1: "F", 2: "F", 3: "F"})

    finished, scores = runner._scan_finished_memgui_pass_at_k_tasks(
        str(tmp_path),
        [task_name],
        pass_at_k=3,
        agent_type="memgui",
        require_request_logs=True,
    )

    assert finished == [task_name]
    assert scores == [0.0]


def test_memgui_finished_scan_reruns_when_any_attempt_request_log_missing(tmp_path):
    task_name = "task-pass3-failed"
    task_dir = tmp_path / task_name
    task_dir.mkdir()
    (task_dir / "result.txt").write_text(
        "score: 0.0\nreason: pass@3: all 3 attempts failed"
    )
    _write_request_logs(tmp_path, task_name, [1, 2])
    _write_attempt_evaluations(tmp_path, task_name, {1: "F", 2: "F", 3: "F"})

    finished, scores = runner._scan_finished_memgui_pass_at_k_tasks(
        str(tmp_path),
        [task_name],
        pass_at_k=3,
        agent_type="memgui",
        require_request_logs=True,
    )

    assert finished == []
    assert scores == []


def test_memgui_finished_scan_reruns_incomplete_pass_at_k_artifacts(tmp_path):
    task_name = "task-incomplete-pass3"
    task_dir = tmp_path / task_name
    task_dir.mkdir()
    (task_dir / "result.txt").write_text(
        "score: 0.0\nreason: pass@3: all 3 attempts failed"
    )
    _write_request_logs(tmp_path, task_name, [1, 2, 3])
    _write_attempt_evaluations(tmp_path, task_name, {1: "F"})

    finished, scores = runner._scan_finished_memgui_pass_at_k_tasks(
        str(tmp_path),
        [task_name],
        pass_at_k=3,
        agent_type="memgui",
        require_request_logs=True,
    )

    assert finished == []
    assert scores == []


def test_memgui_finished_scan_keeps_success_with_complete_attempts(tmp_path):
    task_name = "task-success-attempt2"
    task_dir = tmp_path / task_name
    task_dir.mkdir()
    (task_dir / "result.txt").write_text(
        "score: 1.0\nreason: pass@3: success at attempt 2; attempts_run=2/3"
    )
    _write_request_logs(tmp_path, task_name, [1, 2])
    _write_attempt_evaluations(tmp_path, task_name, {1: "F", 2: "S"})

    finished, scores = runner._scan_finished_memgui_pass_at_k_tasks(
        str(tmp_path),
        [task_name],
        pass_at_k=3,
        agent_type="memgui",
        require_request_logs=True,
    )

    assert finished == [task_name]
    assert scores == [1.0]


def test_memgui_finished_scan_reruns_error_or_corrupt_trajectory(tmp_path):
    task_name = "task-eval-error"
    task_dir = tmp_path / task_name
    task_dir.mkdir()
    (task_dir / "result.txt").write_text("score: 0.0\nreason: pass@1 failure")
    (task_dir / "traj.json").write_text("not-json")
    _write_attempt_evaluations(tmp_path, task_name, {1: "E"})

    finished, scores = runner._scan_finished_memgui_pass_at_k_tasks(
        str(tmp_path),
        [task_name],
        pass_at_k=1,
        agent_type="qwen3vl",
    )

    assert finished == []
    assert scores == []


def test_memgui_finished_scan_reruns_conflicting_aggregate_and_csv(tmp_path):
    task_name = "task-conflicting-result"
    task_dir = tmp_path / task_name
    task_dir.mkdir()
    (task_dir / "result.txt").write_text(
        "score: 1.0\nreason: pass@3: success at attempt 2; attempts_run=2/3"
    )
    _write_request_logs(tmp_path, task_name, [1, 2])
    _write_attempt_evaluations(tmp_path, task_name, {1: "F", 2: "F"})

    finished, scores = runner._scan_finished_memgui_pass_at_k_tasks(
        str(tmp_path),
        [task_name],
        pass_at_k=3,
        agent_type="memgui",
        require_request_logs=True,
    )

    assert finished == []
    assert scores == []


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
