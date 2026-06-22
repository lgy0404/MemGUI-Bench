import json
from types import SimpleNamespace

from mobile_world.agents.base import BaseAgent
from memgui_eval.utils.common import log_and_save_interaction


class DummyAgent(BaseAgent):
    def predict(self, observation):
        raise NotImplementedError


def _response(text: str):
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=None)


def test_raw_openai_request_payload_is_saved(tmp_path):
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return _response("ok")

    agent = DummyAgent()
    agent.openai_client = SimpleNamespace(
        base_url="https://example.test/v1",
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)),
    )
    agent.enable_llm_request_logging(True)
    agent.set_llm_request_log_dir(tmp_path / "llm_requests")

    image_url = "data:image/png;base64,abc123"
    result = agent.openai_chat_completions_create(
        model="debug-model",
        messages=[
            {"role": "system", "content": [{"type": "text", "text": "sys"}]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        temperature=0.0,
    )

    assert result == "ok"
    assert len(calls) == 1
    request_files = sorted((tmp_path / "llm_requests").glob("request_*.json"))
    assert len(request_files) == 1

    payload = json.loads(request_files[0].read_text())
    assert payload["source"] == "action_agent"
    assert payload["agent_class"] == "DummyAgent"
    assert payload["base_url"] == "https://example.test/v1"
    assert payload["request"]["model"] == "debug-model"
    assert payload["request"]["kwargs"] == {"temperature": 0.0}
    assert payload["request"]["messages"][1]["content"][1]["image_url"]["url"] == image_url
    assert "api_key" not in json.dumps(payload).lower()


def test_raw_openai_request_payload_logging_is_opt_in(tmp_path):
    def fake_create(**_kwargs):
        return _response("ok")

    agent = DummyAgent()
    agent.openai_client = SimpleNamespace(
        base_url="https://example.test/v1",
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)),
    )
    agent.set_llm_request_log_dir(tmp_path / "llm_requests")

    agent.openai_chat_completions_create(
        model="debug-model",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert not (tmp_path / "llm_requests").exists()


def test_memgui_eval_raw_request_is_saved_separately_from_prompt_log(tmp_path):
    raw_request = {
        "base_url": "https://eval.example/v1",
        "request": {
            "model": "eval-model",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.01,
        },
    }

    log_and_save_interaction(
        str(tmp_path),
        "final_decision_phase1",
        "system",
        "user",
        "{\"decision\": 1}",
        raw_request=raw_request,
    )

    prompt_logs = json.loads((tmp_path / "prompt_logs.json").read_text())
    assert "raw_request" not in prompt_logs[0]
    assert prompt_logs[0]["source"] == "memgui_eval"
    assert prompt_logs[0]["raw_request_path"].startswith("eval_llm_requests/")
    assert prompt_logs[0]["raw_request_summary"] == {
        "base_url": "https://eval.example/v1",
        "model": "eval-model",
        "temperature": 0.01,
        "message_count": 1,
    }

    request_path = tmp_path / prompt_logs[0]["raw_request_path"]
    request_payload = json.loads(request_path.read_text())
    assert request_payload["source"] == "memgui_eval"
    assert request_payload["request"]["model"] == "eval-model"
