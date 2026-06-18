import pytest
from PIL import Image

from mobile_world.agents.base import TransientLLMError
from mobile_world.agents.implementations import planner_executor
from mobile_world.agents.implementations.planner_executor import PlannerExecutorAgentMCP
from mobile_world.agents.implementations.seed_agent import SeedAgent


class _FakeExecutor:
    def __init__(self, *args, **kwargs):
        pass

    def initialize(self, instruction):
        self.instruction = instruction

    def predict(self, observation):
        raise AssertionError("Executor should not run when planner LLM is transient")

    def reset(self):
        pass


def _observation():
    return {
        "screenshot": Image.new("RGB", (1080, 1920), "white"),
        "tool_call": None,
        "ask_user_response": None,
    }


def test_planner_executor_propagates_transient_llm_error(monkeypatch):
    monkeypatch.setitem(planner_executor.GROUNDING_MODELS, "fake", _FakeExecutor)
    agent = PlannerExecutorAgentMCP(
        model_name="planner",
        llm_base_url="http://llm",
        api_key="key",
        runtime_conf={"history_n_images": 1, "temperature": 0.0, "max_tokens": 64},
        executor_agent_class="fake",
        executor_llm_base_url="http://llm",
        executor_model_name="executor",
        executor_runtime_conf={},
        tools=[],
    )
    agent.initialize("Find the requested item")
    monkeypatch.setattr(
        agent,
        "openai_chat_completions_create",
        lambda **_kwargs: (_ for _ in ()).throw(
            TransientLLMError("Transient LLM error after retries: 429")
        ),
    )

    with pytest.raises(TransientLLMError):
        agent.predict(_observation())


def test_seed_agent_propagates_transient_llm_error(monkeypatch):
    agent = SeedAgent(
        model_name="seed",
        llm_base_url="http://llm",
        api_key="key",
        runtime_conf={"use_thinking": True},
        tools=[],
    )
    agent.initialize("Find the requested item")
    monkeypatch.setattr(
        agent,
        "_inference_with_thinking",
        lambda _messages: (_ for _ in ()).throw(
            TransientLLMError("Transient LLM stream error: 429")
        ),
    )

    with pytest.raises(TransientLLMError):
        agent.predict(_observation())
