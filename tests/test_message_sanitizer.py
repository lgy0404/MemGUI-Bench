import pytest

from mobile_world.agents.base import sanitize_openai_messages


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
