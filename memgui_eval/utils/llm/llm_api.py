# encoding: utf-8
import os
import sys
import uuid
import json
import base64
import time
from openai import OpenAI
from dotenv import dotenv_values

# Add project root to path for config_loader import
_project_root = os.path.join(os.path.dirname(__file__), "../../..")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config_loader import get_config


def _normalize_optional(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "none", "null"}:
        return None
    return value


def _load_env_values():
    file_values = dotenv_values(os.path.join(os.getcwd(), ".env"))
    return {**file_values, **os.environ}


try:
    # Use get_config() to get cached config with mode presets applied
    _config = get_config(verbose=False)
    MEMGUI_API_KEY = _config.get("MEMGUI_API_KEY")
    # 步骤描述的配置 - 使用模式预设后的值
    MEMGUI_STEP_DESC_BASE_URL = _config.get("MEMGUI_STEP_DESC_BASE_URL")
    MEMGUI_STEP_DESC_MODEL = _config.get("MEMGUI_STEP_DESC_MODEL")
    # 最终决策的配置 - 使用模式预设后的值
    MEMGUI_FINAL_DECISION_BASE_URL = _config.get("MEMGUI_FINAL_DECISION_BASE_URL")
    MEMGUI_FINAL_DECISION_MODEL = _config.get("MEMGUI_FINAL_DECISION_MODEL")
except Exception as e:
    # 如果读取配置失败，fallback到 .env / 环境变量（仅通用变量，无默认 URL）
    print(
        f"Warning: Failed to load optional config file, falling back to environment variables: {e}"
    )
    _env_values = _load_env_values()
    MEMGUI_API_KEY = _env_values.get("MEMGUI_API_KEY")
    MEMGUI_STEP_DESC_BASE_URL = _env_values.get("MEMGUI_STEP_DESC_BASE_URL")
    MEMGUI_STEP_DESC_MODEL = _env_values.get("MEMGUI_STEP_DESC_MODEL")
    MEMGUI_FINAL_DECISION_BASE_URL = _env_values.get("MEMGUI_FINAL_DECISION_BASE_URL")
    MEMGUI_FINAL_DECISION_MODEL = _env_values.get("MEMGUI_FINAL_DECISION_MODEL")

BASE_URL = _normalize_optional(_load_env_values().get("BASE_URL"))
MEMGUI_STEP_DESC_BASE_URL = _normalize_optional(MEMGUI_STEP_DESC_BASE_URL) or BASE_URL
MEMGUI_FINAL_DECISION_BASE_URL = _normalize_optional(MEMGUI_FINAL_DECISION_BASE_URL) or BASE_URL

if not MEMGUI_API_KEY:
    raise ValueError(
        "MEMGUI_API_KEY not found in .env or environment variables"
    )
if not MEMGUI_FINAL_DECISION_BASE_URL:
    raise ValueError(
        "MEMGUI_FINAL_DECISION_BASE_URL is not set in .env or environment variables, "
        "and BASE_URL is also empty"
    )

# 客户端缓存，避免重复创建
_client_cache = {}


def _get_client(base_url):
    """获取或创建指定 base_url 的 OpenAI 客户端"""
    if base_url not in _client_cache:
        _client_cache[base_url] = OpenAI(base_url=base_url, api_key=MEMGUI_API_KEY)
    return _client_cache[base_url]


# 默认客户端（兼容旧代码）
client = _get_client(MEMGUI_FINAL_DECISION_BASE_URL)

# Model pricing (USD per million tokens)
MODEL_PRICING = {
    "gemini-2.5-pro": {
        "input_price_per_million": 1.25,
        "output_price_per_million": 10.0,
    },
    "gemini-2.5-flash": {
        "input_price_per_million": 0.3,
        "output_price_per_million": 2.5,
    },
    "gemini-1.5-pro-001": {
        "input_price_per_million": 1.25,
        "output_price_per_million": 5.0,
    },
    "gemini-1.5-pro-002": {
        "input_price_per_million": 1.25,
        "output_price_per_million": 5.0,
    },
    "qwen-vl-max-2025-01-25": {
        "input_price_per_million": 2.0,
        "output_price_per_million": 6.0,
    },
    "qwen-vl-max-2024-12-30": {
        "input_price_per_million": 2.0,
        "output_price_per_million": 6.0,
    },
}

# Default values for backward compatibility (model from config, no hardcoded default)
DEFAULT_MAX_RETRIES = 200
DEFAULT_RETRY_DELAY = 2
DEFAULT_MODEL = MEMGUI_FINAL_DECISION_MODEL
# max_tokens is intentionally not set - let the model use its default
DEFAULT_TEMPERATURE = 0.01


def _is_non_retryable_api_error(error):
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    return status_code is not None and 400 <= int(status_code) < 500


def _retry_or_raise(error, retry_count, max_retries, retry_delay):
    print(f"发生异常: {str(error)}")
    if _is_non_retryable_api_error(error):
        raise RuntimeError(
            "MemGUI-Eval request failed with a non-retryable HTTP 4xx error. "
            "Please check MEMGUI_*_MODEL and MEMGUI_*_BASE_URL in .env."
        ) from error

    retry_count += 1
    if retry_count >= max_retries:
        raise RuntimeError(
            f"MemGUI-Eval request failed after {max_retries} retries"
        ) from error

    print(f"请求异常，{retry_delay}秒后进行第{retry_count}次重试...")
    time.sleep(retry_delay)
    return retry_count


def _retry_empty_or_raise(retry_count, max_retries, retry_delay):
    print("响应内容为空")
    retry_count += 1
    if retry_count >= max_retries:
        raise RuntimeError(f"MemGUI-Eval returned empty responses after {max_retries} retries")
    print(f"将在{retry_delay}秒后进行第{retry_count}次重试...")
    time.sleep(retry_delay)
    return retry_count


def extract_token_usage(usage_info):
    """Extract token usage from API response."""
    if not usage_info:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    prompt_tokens = usage_info.get("prompt_tokens", 0)
    completion_tokens = usage_info.get("completion_tokens", 0)
    total_tokens = usage_info.get("total_tokens", prompt_tokens + completion_tokens)

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def calculate_api_cost(usage_info, model):
    """Calculate API cost based on token usage and model pricing."""
    if model not in MODEL_PRICING:
        return 0.0

    pricing = MODEL_PRICING[model]
    extracted_usage = extract_token_usage(usage_info)
    prompt_tokens = extracted_usage["prompt_tokens"]
    completion_tokens = extracted_usage["completion_tokens"]

    input_cost = (prompt_tokens / 1_000_000) * pricing["input_price_per_million"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output_price_per_million"]

    return input_cost + output_cost


def inference_chat_gemini_2_image(
    system_prompt,
    user_prompt,
    image1,
    image2,
    max_retries=DEFAULT_MAX_RETRIES,
    retry_delay=DEFAULT_RETRY_DELAY,
    model=DEFAULT_MODEL,
    provider=None,  # Not used in new format
    max_tokens=None,  # Don't set max_tokens by default - let model use its own default
    temperature=0.01,
    app_id=None,  # Not used in new format
    app_key=None,  # Not used in new format
    api_url=None,  # Not used in new format
):
    """
    使用 OpenAI 兼容的客户端进行对话推理，并上传两张图片（文件路径）。
    返回服务端的回复内容，会一直重试直到成功获取有效回复。
    """
    # 从本地读取并转换图片为 Base64
    with open(image1, "rb") as f:
        image1_base64 = base64.b64encode(f.read()).decode("utf-8")

    with open(image2, "rb") as f:
        image2_base64 = base64.b64encode(f.read()).decode("utf-8")

    retry_count = 0
    while True:
        try:
            # Build API call parameters
            api_params = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image1_base64}"
                                },
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image2_base64}"
                                },
                            },
                        ],
                    },
                ],
                "temperature": temperature,
            }

            # Only add max_tokens if explicitly provided
            if max_tokens is not None:
                api_params["max_tokens"] = max_tokens

            completion = client.chat.completions.create(**api_params)

            content = completion.choices[0].message.content
            if content:
                usage_info = (
                    completion.usage.__dict__
                    if hasattr(completion.usage, "__dict__")
                    else {}
                )
                extracted_usage = extract_token_usage(usage_info)
                api_cost = calculate_api_cost(usage_info, model)

                result = {
                    "content": content,
                    "usage": extracted_usage,
                    "model": model,
                    "provider": "openai_compatible",
                    "api_cost": api_cost,
                }

                return result
            else:
                retry_count = _retry_empty_or_raise(
                    retry_count, max_retries, retry_delay
                )
                continue

        except Exception as e:
            retry_count = _retry_or_raise(e, retry_count, max_retries, retry_delay)
            continue


def inference_chat_gemini_1_image(
    system_prompt,
    user_prompt,
    image1,
    max_retries=DEFAULT_MAX_RETRIES,
    retry_delay=DEFAULT_RETRY_DELAY,
    model=DEFAULT_MODEL,
    provider=None,  # Not used in new format
    max_tokens=None,  # Don't set max_tokens by default - let model use its own default
    temperature=DEFAULT_TEMPERATURE,
    app_id=None,  # Not used in new format
    app_key=None,  # Not used in new format
    api_url=None,  # 支持指定 base_url
):
    """
    使用 OpenAI 兼容的客户端进行对话推理，并上传一张图片（文件路径）。
    返回服务端的回复内容，会一直重试直到成功获取有效回复。

    Args:
        api_url: 可选，指定 API 的 base_url。如果不指定，使用默认的 MEMGUI_FINAL_DECISION_BASE_URL
    """
    # 根据 api_url 获取对应的客户端
    if api_url:
        api_client = _get_client(api_url)
    else:
        api_client = client

    # 从本地读取并转换图片为 Base64
    with open(image1, "rb") as f:
        image1_base64 = base64.b64encode(f.read()).decode("utf-8")

    retry_count = 0
    while True:
        try:
            # Build API call parameters
            api_params = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image1_base64}"
                                },
                            },
                        ],
                    },
                ],
                "temperature": temperature,
            }

            # Only add max_tokens if explicitly provided
            if max_tokens is not None:
                api_params["max_tokens"] = max_tokens

            completion = api_client.chat.completions.create(**api_params)

            content = completion.choices[0].message.content
            if content:
                usage_info = (
                    completion.usage.__dict__
                    if hasattr(completion.usage, "__dict__")
                    else {}
                )
                extracted_usage = extract_token_usage(usage_info)
                api_cost = calculate_api_cost(usage_info, model)

                result = {
                    "content": content,
                    "usage": extracted_usage,
                    "model": model,
                    "provider": "openai_compatible",
                    "api_cost": api_cost,
                }

                return result
            else:
                retry_count = _retry_empty_or_raise(
                    retry_count, max_retries, retry_delay
                )
                continue

        except Exception as e:
            retry_count = _retry_or_raise(e, retry_count, max_retries, retry_delay)
            continue


def inference_chat_gemini_wo_image(
    system_prompt,
    user_prompt,
    max_retries=DEFAULT_MAX_RETRIES,
    retry_delay=DEFAULT_RETRY_DELAY,
    model=DEFAULT_MODEL,
    provider=None,  # Not used in new format
    max_tokens=None,  # Don't set max_tokens by default - let model use its own default
    temperature=0.01,
    app_id=None,  # Not used in new format
    app_key=None,  # Not used in new format
    api_url=None,  # Not used in new format
):
    """
    使用 OpenAI 兼容的客户端进行对话推理，不传入图片。
    返回服务端的回复内容，会一直重试直到成功获取有效回复。
    """
    retry_count = 0
    while True:
        try:
            # Build API call parameters
            api_params = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
            }

            # Only add max_tokens if explicitly provided
            if max_tokens is not None:
                api_params["max_tokens"] = max_tokens

            completion = client.chat.completions.create(**api_params)

            content = completion.choices[0].message.content
            if content:
                usage_info = (
                    completion.usage.__dict__
                    if hasattr(completion.usage, "__dict__")
                    else {}
                )
                extracted_usage = extract_token_usage(usage_info)
                api_cost = calculate_api_cost(usage_info, model)

                result = {
                    "content": content,
                    "usage": extracted_usage,
                    "model": model,
                    "provider": "openai_compatible",
                    "api_cost": api_cost,
                }

                return result
            else:
                retry_count = _retry_empty_or_raise(
                    retry_count, max_retries, retry_delay
                )
                continue

        except Exception as e:
            retry_count = _retry_or_raise(e, retry_count, max_retries, retry_delay)
            continue
