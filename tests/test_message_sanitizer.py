from types import SimpleNamespace

import pytest

from mobile_world.agents.base import BaseAgent, sanitize_openai_messages


class DummyAgent(BaseAgent):
    def predict(self, observation):
        raise NotImplementedError


def _response(text: str):
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=None)


def test_sanitize_messages_replaces_empty_text_parts_and_drops_empty_assistant():
    messages = [
        {"role": "system", "content": ""},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": ""}],
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "   "},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        },
    ]

    sanitized = sanitize_openai_messages(messages)

    assert sanitized[0]["content"] == "(system message intentionally left empty)"
    assert len(sanitized) == 2
    assert sanitized[1]["content"][0]["text"] == "(user message intentionally left empty)"


def test_sanitize_messages_rejects_empty_image_url():
    with pytest.raises(ValueError, match="image_url.url"):
        sanitize_openai_messages(
            [{"role": "user", "content": [{"type": "image_url", "image_url": {}}]}]
        )


def test_image_detail_auto_rejection_retries_with_high_detail():
    agent = DummyAgent()
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError(
                "Error code: 400 - invalid params, invalid image detail: auto (2013)"
            )
        return _response('Thought: ok\nAction: {"action_type":"wait"}')

    agent.openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )

    result = agent.openai_chat_completions_create(
        model="model",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
                ],
            }
        ],
    )

    assert result.startswith("Thought: ok")
    assert len(calls) == 2
    first_image = calls[0]["messages"][0]["content"][0]["image_url"]
    second_image = calls[1]["messages"][0]["content"][0]["image_url"]
    assert "detail" not in first_image
    assert second_image["detail"] == "high"
