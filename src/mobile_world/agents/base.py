"""
Base agent interface for mobile automation.
"""

import copy
import os
import random
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from loguru import logger
from openai import OpenAI

from mobile_world.runtime.utils.models import JSONAction


class TransientLLMError(RuntimeError):
    """Raised when the LLM backend fails with a retryable infrastructure error."""

    def __init__(self, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


_LLM_RATE_LIMIT_DEFAULT_RETRIES = int(os.getenv("MEMGUI_LLM_RATE_LIMIT_RETRIES", "20"))
_LLM_RATE_LIMIT_DEFAULT_MAX_WAIT = float(
    os.getenv("MEMGUI_LLM_RATE_LIMIT_MAX_WAIT", "120")
)
_LLM_MAX_CONCURRENCY = max(1, int(os.getenv("MEMGUI_LLM_MAX_CONCURRENCY", "2")))
_LLM_SEMAPHORE = threading.BoundedSemaphore(_LLM_MAX_CONCURRENCY)
_LLM_STATE_LOCK = threading.Lock()
_LLM_COOLDOWN_UNTIL = 0.0
_LLM_STATS = {
    "rate_limit_count": 0,
    "transient_error_count": 0,
    "non_transient_error_count": 0,
    "retry_sleep_seconds": 0.0,
}


def configure_llm_rate_limits(
    *,
    max_concurrency: int | None = None,
    rate_limit_retries: int | None = None,
    rate_limit_max_wait: float | None = None,
    reset_stats: bool = False,
) -> None:
    """Configure process-wide LLM throttling for threaded benchmark runs."""
    global _LLM_MAX_CONCURRENCY, _LLM_SEMAPHORE
    global _LLM_RATE_LIMIT_DEFAULT_RETRIES, _LLM_RATE_LIMIT_DEFAULT_MAX_WAIT

    with _LLM_STATE_LOCK:
        if max_concurrency is not None:
            _LLM_MAX_CONCURRENCY = max(1, int(max_concurrency))
            _LLM_SEMAPHORE = threading.BoundedSemaphore(_LLM_MAX_CONCURRENCY)
        if rate_limit_retries is not None:
            _LLM_RATE_LIMIT_DEFAULT_RETRIES = max(1, int(rate_limit_retries))
        if rate_limit_max_wait is not None:
            _LLM_RATE_LIMIT_DEFAULT_MAX_WAIT = max(1.0, float(rate_limit_max_wait))
        if reset_stats:
            for key in _LLM_STATS:
                _LLM_STATS[key] = 0.0 if key.endswith("_seconds") else 0


def get_llm_rate_limit_stats() -> dict[str, int | float]:
    with _LLM_STATE_LOCK:
        return dict(_LLM_STATS)


def _record_llm_stat(key: str, amount: int | float = 1) -> None:
    with _LLM_STATE_LOCK:
        _LLM_STATS[key] = _LLM_STATS.get(key, 0) + amount


def _set_global_llm_cooldown(seconds: float) -> None:
    global _LLM_COOLDOWN_UNTIL
    if seconds <= 0:
        return
    with _LLM_STATE_LOCK:
        _LLM_COOLDOWN_UNTIL = max(_LLM_COOLDOWN_UNTIL, time.monotonic() + seconds)


def _wait_for_global_llm_cooldown() -> None:
    while True:
        with _LLM_STATE_LOCK:
            remaining = _LLM_COOLDOWN_UNTIL - time.monotonic()
        if remaining <= 0:
            return
        wait_seconds = min(remaining, 5.0)
        _record_llm_stat("retry_sleep_seconds", wait_seconds)
        time.sleep(wait_seconds)


def _is_transient_llm_exception(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 409, 429, 500, 502, 503, 504}:
        return True

    text = str(exc).lower()
    transient_markers = [
        "429",
        "toomanyrequests",
        "too many requests",
        "rate limit",
        "internalservererror",
        "connection error",
        "readtimeout",
        "timeout",
        "temporarily unavailable",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
    ]
    return any(marker in text for marker in transient_markers)


def _is_rate_limit_exception(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    text = str(exc).lower()
    return status_code == 429 or "429" in text or "too many requests" in text or "rate limit" in text


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _compute_transient_wait(
    exc: Exception,
    attempt_index: int,
    max_wait: float,
) -> float:
    retry_after = _retry_after_seconds(exc)
    if retry_after is not None:
        return min(max_wait, retry_after)
    base = min(max_wait, 2.0**min(attempt_index, 6))
    jitter = random.uniform(0.0, min(1.0, base * 0.25))
    return min(max_wait, base + jitter)


def _sanitize_text_value(value: Any, placeholder: str) -> str:
    if value is None:
        return placeholder
    text = str(value)
    return text if text.strip() else placeholder


def sanitize_openai_messages(messages: list[dict]) -> list[dict]:
    """Return OpenAI messages without empty text content or malformed image parts."""
    sanitized: list[dict] = []
    for original_message in copy.deepcopy(messages):
        message = dict(original_message)
        role = message.get("role", "user")
        placeholder = f"({role} message intentionally left empty)"
        content = message.get("content")
        if isinstance(content, str):
            if role == "assistant" and not content.strip():
                continue
            message["content"] = _sanitize_text_value(content, placeholder)
            sanitized.append(message)
            continue
        if not isinstance(content, list):
            if role == "assistant":
                continue
            message["content"] = placeholder
            sanitized.append(message)
            continue

        new_parts: list[dict] = []
        for part in content:
            if not isinstance(part, dict):
                if role == "assistant" and not str(part).strip():
                    continue
                new_parts.append({"type": "text", "text": _sanitize_text_value(part, placeholder)})
                continue
            part_type = part.get("type")
            if part_type == "text":
                text_part = dict(part)
                if role == "assistant" and not str(text_part.get("text") or "").strip():
                    continue
                text_part["text"] = _sanitize_text_value(
                    text_part.get("text"), placeholder
                )
                new_parts.append(text_part)
            elif part_type == "image_url":
                image_url = part.get("image_url")
                url = image_url.get("url") if isinstance(image_url, dict) else None
                if not isinstance(url, str) or not url.strip():
                    raise ValueError("Invalid OpenAI message: image_url.url must be non-empty")
                new_parts.append(part)
            else:
                new_parts.append(part)
        if role == "assistant" and not new_parts:
            continue
        message["content"] = new_parts or [{"type": "text", "text": placeholder}]
        sanitized.append(message)
    return sanitized


class BaseAgent(ABC):
    """Abstract base class for all mobile automation agents."""

    def __init__(
        self,
        *args: Any,
        **kwargs: Any,
    ):
        self._total_completion_tokens: int = 0
        self._total_prompt_tokens: int = 0
        self._total_cached_tokens: int = 0

    def initialize(self, instruction: str) -> bool:
        """Initialize the agent with the given instruction."""
        self.instruction = instruction
        logger.debug(f"initialized the agent with the given instruction: {self.instruction}")
        self.initialize_hook(self.instruction)
        return True

    def initialize_hook(self, instruction: str) -> None:
        """Hook for initializing the agent."""
        pass

    @abstractmethod
    def predict(self, observation: dict[str, Any]) -> tuple[str, JSONAction]:
        """Generate the next action based on current observation."""
        raise NotImplementedError("predict method is not implemented")

    def done(self) -> None:
        """finalize the agent for the current task."""
        logger.debug(f"finalizing the agent for the current task: {self.instruction}")
        self.instruction = None
        self.reset()

    def reset(self) -> None:
        """Reset the agent for the next task."""
        logger.warning(
            "reset method is not implemented, note the agent memory will be carried over to the next task"
        )
        pass

    def build_openai_client(self, base_url: str, api_key: str) -> None:
        """Build the OpenAI client."""
        self.openai_client = OpenAI(
            base_url=base_url,
            api_key=api_key if api_key else "empty",
            timeout=120.0,
        )
        logger.debug(f"built the OpenAI client with base_url={base_url}")

    def _wrap_stream_with_usage_logging(self, stream: Any) -> Any:
        """Wrap a streaming response to log usage when stream completes."""
        final_usage = None
        try:
            for chunk in stream:
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    final_usage = chunk
                yield chunk
        except Exception as e:
            if _is_transient_llm_exception(e):
                _record_llm_stat("transient_error_count")
                if _is_rate_limit_exception(e):
                    _record_llm_stat("rate_limit_count")
                raise TransientLLMError(
                    f"Transient LLM stream error: {e}",
                    retry_after=_retry_after_seconds(e),
                ) from e
            raise

        if final_usage is not None:
            self._log_openai_usage(final_usage)

    def openai_chat_completions_create(
        self,
        model: str,
        messages: list[dict],
        retry_times: int = 3,
        stream: bool = False,
        **kwargs: Any,
    ) -> str:
        transient_retries = int(kwargs.pop("rate_limit_retries", _LLM_RATE_LIMIT_DEFAULT_RETRIES))
        max_wait = float(kwargs.pop("rate_limit_max_wait", _LLM_RATE_LIMIT_DEFAULT_MAX_WAIT))
        messages = sanitize_openai_messages(messages)

        last_error: Exception | None = None
        non_transient_attempts_left = retry_times
        transient_attempt = 0
        while non_transient_attempts_left > 0:
            try:
                if "claude" in model:
                    kwargs["max_tokens"] = 64000

                if "gpt" in model.lower() or "o1" in model.lower():
                    if "max_tokens" in kwargs:
                        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

                if "k2.5" in model.lower():
                    kwargs["extra_body"] = {"enable_thinking": True}

                _wait_for_global_llm_cooldown()
                with _LLM_SEMAPHORE:
                    if stream:
                        kwargs.setdefault("stream_options", {})
                        kwargs["stream_options"]["include_usage"] = True
                        response = self.openai_client.chat.completions.create(
                            model=model,
                            messages=messages,
                            **kwargs,
                            stream=True,
                        )
                        return self._wrap_stream_with_usage_logging(response)

                    response = self.openai_client.chat.completions.create(
                        model=model,
                        messages=messages,
                        **kwargs,
                    )

                self._log_openai_usage(response)
                content = response.choices[0].message.content
                final_content = content.strip() if isinstance(content, str) else ""
                # for k2.5, we keep its reasoning_content
                if (
                    "k2.5" in model.lower()
                    and hasattr(response.choices[0].message, "reasoning_content")
                    and response.choices[0].message.reasoning_content
                ):
                    final_content = f"<think>{response.choices[0].message.reasoning_content.strip()}</think>\n{final_content}"
                if not final_content:
                    raise RuntimeError("OpenAI API returned an empty message content")
                return final_content
            except Exception as e:
                last_error = e
                error_msg = str(e)
                logger.warning(f"Error calling OpenAI API: {e}")

                # Check if error is about max_tokens parameter and retry with max_completion_tokens
                if "max_tokens" in error_msg and "max_completion_tokens" in error_msg:
                    if "max_tokens" in kwargs:
                        logger.info("Retrying with max_completion_tokens instead of max_tokens")
                        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                        continue  # Retry immediately without decrementing retry_times

                if _is_transient_llm_exception(e):
                    transient_attempt += 1
                    _record_llm_stat("transient_error_count")
                    if _is_rate_limit_exception(e):
                        _record_llm_stat("rate_limit_count")
                    if transient_attempt > transient_retries:
                        raise TransientLLMError(
                            f"Transient LLM error after {transient_retries} retries: {e}",
                            retry_after=_retry_after_seconds(e),
                        ) from e
                    wait_seconds = _compute_transient_wait(
                        e,
                        transient_attempt,
                        max_wait,
                    )
                    logger.warning(
                        "Transient LLM error; retrying after {:.1f}s ({}/{})",
                        wait_seconds,
                        transient_attempt,
                        transient_retries,
                    )
                    _set_global_llm_cooldown(wait_seconds)
                    _record_llm_stat("retry_sleep_seconds", wait_seconds)
                    time.sleep(wait_seconds)
                    continue

                _record_llm_stat("non_transient_error_count")
                non_transient_attempts_left -= 1
                if non_transient_attempts_left > 0:
                    time.sleep(1)

        raise RuntimeError(f"OpenAI API call failed after retries: {last_error}")

    def _log_openai_usage(self, response: Any) -> None:
        """Log and track the usage of the OpenAI API."""
        if response.usage is None:
            return

        completion_tokens = response.usage.completion_tokens or 0
        prompt_tokens = response.usage.prompt_tokens or 0
        cached_tokens = 0

        if (
            hasattr(response.usage, "prompt_tokens_details")
            and response.usage.prompt_tokens_details
        ):
            cached_tokens = response.usage.prompt_tokens_details.cached_tokens or 0

        self._total_completion_tokens += completion_tokens
        self._total_prompt_tokens += prompt_tokens
        self._total_cached_tokens += cached_tokens

        logger.debug(
            f"OpenAI API usage: completion={completion_tokens}, prompt={prompt_tokens}, "
            f"cached={cached_tokens} | Total: completion={self._total_completion_tokens}, "
            f"prompt={self._total_prompt_tokens}, cached={self._total_cached_tokens}"
        )

    def get_total_token_usage(self) -> dict[str, int]:
        """Get the total token usage across all API calls."""
        return {
            "completion_tokens": self._total_completion_tokens,
            "prompt_tokens": self._total_prompt_tokens,
            "cached_tokens": self._total_cached_tokens,
            "total_tokens": self._total_completion_tokens + self._total_prompt_tokens,
        }

    def reset_token_usage(self) -> None:
        """Reset the token usage counters."""
        self._total_completion_tokens = 0
        self._total_prompt_tokens = 0
        self._total_cached_tokens = 0


class MCPAgent(BaseAgent):
    def __init__(
        self,
        tools: list[dict],
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.tools = tools

    def initialize(self, instruction: str) -> bool:
        """Initialize the agent with the given instruction."""
        self.instruction = instruction

        self.initialize_hook(self.instruction)
        logger.debug(f"initialized the agent with the given instruction: {self.instruction}")
        return True

    def reset_tools(self, tools: list[dict]) -> None:
        """Reset the tools for the agent."""
        self.tools = tools

    @abstractmethod
    def predict(self, observation: dict[str, Any]) -> tuple[str, JSONAction]:
        """Generate the next action based on current observation."""
        raise NotImplementedError("predict method is not implemented")
