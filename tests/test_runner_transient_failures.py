import json
from queue import Queue
from types import SimpleNamespace

from mobile_world.agents.base import TransientLLMError
from mobile_world.core import runner


def _agent():
    return SimpleNamespace(done=lambda: None)


def _env():
    return SimpleNamespace(
        base_url="http://env-0",
        tear_down_task=lambda task_type: SimpleNamespace(status="success"),
    )


def _queue_with_env():
    env_queue = Queue()
    env_queue.put((_env(), "container-0"))
    return env_queue


def test_transient_llm_retry_does_not_consume_pass_at_k_attempt(monkeypatch, tmp_path):
    executed_attempts = []

    monkeypatch.setattr(runner, "_resolve_task_max_step", lambda *args, **kwargs: 5)
    monkeypatch.setattr(runner, "create_agent", lambda *args, **kwargs: _agent())

    def fake_execute_single_task(*args, **kwargs):
        attempt_num = kwargs["attempt_num"]
        executed_attempts.append(attempt_num)
        if len(executed_attempts) == 1:
            raise TransientLLMError("Transient LLM error after retries: 429")
        return 2, 1.0, "success after transient retry"

    monkeypatch.setattr(runner, "_execute_single_task", fake_execute_single_task)

    result = runner._process_task_on_env(
        task_name="001-FindProductAndFilter",
        env_queue=_queue_with_env(),
        agent_type="qwen3vl",
        model_name="model",
        llm_base_url="http://llm",
        api_key="key",
        log_file_root=str(tmp_path),
        max_step=None,
        suite_family="memgui_bench",
        pass_at_k=3,
        llm_infra_retries=2,
    )

    assert executed_attempts == [1, 1]
    assert result["score"] == 1.0
    assert [item["attempt"] for item in result["attempts"]] == [1]

    result_text = (tmp_path / "001-FindProductAndFilter" / "result.txt").read_text()
    assert "pass@3: success at attempt 1" in result_text
    assert not (tmp_path / "_infra_failures").exists()


def test_transient_llm_exhaustion_marks_no_result_without_score(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_resolve_task_max_step", lambda *args, **kwargs: 5)
    monkeypatch.setattr(runner, "create_agent", lambda *args, **kwargs: _agent())
    monkeypatch.setattr(
        runner,
        "_execute_single_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            TransientLLMError("Transient LLM error after retries: 429")
        ),
    )

    result = runner._process_task_on_env(
        task_name="003-RecordAndNameAudio",
        env_queue=_queue_with_env(),
        agent_type="general_e2e",
        model_name="model",
        llm_base_url="http://llm",
        api_key="key",
        log_file_root=str(tmp_path),
        max_step=None,
        suite_family="memgui_bench",
        pass_at_k=3,
        llm_infra_retries=1,
    )

    assert result is None
    assert not (tmp_path / "003-RecordAndNameAudio" / "result.txt").exists()

    failure = json.loads(
        (
            tmp_path
            / "_infra_failures"
            / "003-RecordAndNameAudio"
            / "attempt_1.json"
        ).read_text()
    )
    assert failure["failure_type"] == "llm_transient"
    assert failure["infra_retries"] == 2

    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["infra_failed_tasks"] == ["003-RecordAndNameAudio"]
    assert metadata["infra_failure_counts"]["llm_transient"] == 1


def test_device_unhealthy_exhaustion_marks_no_result_without_score(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "_resolve_task_max_step", lambda *args, **kwargs: 5)
    monkeypatch.setattr(runner, "create_agent", lambda *args, **kwargs: _agent())
    monkeypatch.setattr(
        runner,
        "_execute_single_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("Device is not healthy; emulator recovery in_progress")
        ),
    )

    result = runner._process_task_on_env(
        task_name="017-SearchAndCompareRatings",
        env_queue=_queue_with_env(),
        agent_type="general_e2e",
        model_name="model",
        llm_base_url="http://llm",
        api_key="key",
        log_file_root=str(tmp_path),
        max_step=None,
        suite_family="memgui_bench",
        pass_at_k=3,
        retry_on_device_unhealthy=0,
        llm_infra_retries=0,
    )

    assert result is None
    assert not (tmp_path / "017-SearchAndCompareRatings" / "result.txt").exists()

    failure = json.loads(
        (
            tmp_path
            / "_infra_failures"
            / "017-SearchAndCompareRatings"
            / "attempt_1.json"
        ).read_text()
    )
    assert failure["failure_type"] == "device_unhealthy"
