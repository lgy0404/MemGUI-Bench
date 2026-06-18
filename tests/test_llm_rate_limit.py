from types import SimpleNamespace

import pytest

from mobile_world.agents import base
from mobile_world.agents.base import (
    BaseAgent,
    TransientLLMError,
    configure_llm_rate_limits,
)


class DummyAgent(BaseAgent):
    def predict(self, observation):
        raise NotImplementedError


def _response(text: str):
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=None)


def test_429_raises_transient_error_instead_of_returning_none(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda _seconds: None)
    configure_llm_rate_limits(
        max_concurrency=1,
        rate_limit_retries=2,
        rate_limit_max_wait=1,
        reset_stats=True,
    )
    agent = DummyAgent()
    calls = {"count": 0}

    def fake_create(**_kwargs):
        calls["count"] += 1
        raise RuntimeError("Error code: 429 - TooManyRequests")

    agent.openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    with pytest.raises(TransientLLMError):
        agent.openai_chat_completions_create(
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )

    assert calls["count"] == 3
    stats = base.get_llm_rate_limit_stats()
    assert stats["rate_limit_count"] == 3


def test_429_then_success_returns_content(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda _seconds: None)
    configure_llm_rate_limits(
        max_concurrency=1,
        rate_limit_retries=2,
        rate_limit_max_wait=1,
        reset_stats=True,
    )
    agent = DummyAgent()
    calls = {"count": 0}

    def fake_create(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("Error code: 429 - TooManyRequests")
        return _response("Thought: ok\nAction: {\"action_type\":\"wait\"}")

    agent.openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    result = agent.openai_chat_completions_create(
        model="model",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert result.startswith("Thought: ok")
    assert calls["count"] == 2


def test_empty_content_raises_transient_error(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda _seconds: None)
    configure_llm_rate_limits(
        max_concurrency=1,
        rate_limit_retries=1,
        rate_limit_max_wait=1,
        reset_stats=True,
    )
    agent = DummyAgent()

    def fake_create(**_kwargs):
        return _response("")

    agent.openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    with pytest.raises(TransientLLMError):
        agent.openai_chat_completions_create(
            model="model",
            messages=[{"role": "user", "content": "hello"}],
        )

    stats = base.get_llm_rate_limit_stats()
    assert stats["transient_error_count"] == 2
    assert stats["rate_limit_count"] == 0


def test_streaming_429_raises_transient_error(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda _seconds: None)
    configure_llm_rate_limits(
        max_concurrency=1,
        rate_limit_retries=1,
        rate_limit_max_wait=1,
        reset_stats=True,
    )
    agent = DummyAgent()

    def failing_stream():
        raise RuntimeError("Error code: 429 - TooManyRequests")
        yield

    def fake_create(**_kwargs):
        return failing_stream()

    agent.openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    completion = agent.openai_chat_completions_create(
        model="model",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )

    with pytest.raises(TransientLLMError):
        list(completion)
