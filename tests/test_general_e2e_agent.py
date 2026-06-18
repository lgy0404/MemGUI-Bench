from PIL import Image

from mobile_world.agents.implementations.general_e2e_agent import GeneralE2EAgentMCP


def test_invalid_action_json_is_model_format_error(monkeypatch):
    agent = GeneralE2EAgentMCP(
        model_name="model",
        llm_base_url="http://llm",
        api_key="key",
        runtime_conf={"history_n_images": 1, "temperature": 0.0, "max_tokens": 64},
        tools=[],
    )
    agent.initialize("Find the requested item")
    monkeypatch.setattr(
        agent,
        "openai_chat_completions_create",
        lambda **_kwargs: 'Thought: click item\nAction: {"action_type": "click", "coordinate": [736, 088]}',
    )

    prediction, action = agent.predict(
        {
            "screenshot": Image.new("RGB", (1080, 1920), "white"),
            "tool_call": None,
            "ask_user_response": None,
        }
    )

    assert "Model output format error" in prediction
    assert action.action_type == "unknown"
    assert "Model output format error" in action.text
