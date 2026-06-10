# encoding: utf-8
"""
LLM API调用的配置文件
从config.yaml中读取模型配置，支持模式预设系统
"""

import os
import sys

# Add project root to path for config_loader import
_project_root = os.path.join(os.path.dirname(__file__), "../../..")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import dotenv_values

from config_loader import get_config


def _normalize_optional(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "none", "null"}:
        return None
    return value


def _env_config():
    file_values = dotenv_values(os.path.join(os.getcwd(), ".env"))
    values = {**file_values, **os.environ}
    base_url = _normalize_optional(values.get("BASE_URL"))
    return {
        "MEMGUI_STEP_DESC_MODEL": _normalize_optional(
            values.get("MEMGUI_STEP_DESC_MODEL")
        ),
        "MEMGUI_STEP_DESC_PROVIDER": _normalize_optional(
            values.get("MEMGUI_STEP_DESC_PROVIDER")
        )
        or "openai_compatible",
        "MEMGUI_STEP_DESC_BASE_URL": _normalize_optional(
            values.get("MEMGUI_STEP_DESC_BASE_URL")
        )
        or base_url,
        "MEMGUI_FINAL_DECISION_MODEL": _normalize_optional(
            values.get("MEMGUI_FINAL_DECISION_MODEL")
        ),
        "MEMGUI_FINAL_DECISION_PROVIDER": _normalize_optional(
            values.get("MEMGUI_FINAL_DECISION_PROVIDER")
        )
        or "openai_compatible",
        "MEMGUI_FINAL_DECISION_BASE_URL": _normalize_optional(
            values.get("MEMGUI_FINAL_DECISION_BASE_URL")
        )
        or base_url,
        "MEMGUI_API_KEY": _normalize_optional(values.get("MEMGUI_API_KEY")),
        "MEMGUI_MAX_RETRIES": int(
            _normalize_optional(values.get("MEMGUI_MAX_RETRIES")) or 4
        ),
    }


try:
    # Use get_config() to get cached config with mode presets applied
    _config = get_config(verbose=False)
except FileNotFoundError:
    _config = _env_config()
except Exception as e:
    print(f"Warning: Failed to load config.yaml, falling back to environment variables: {e}")
    _config = _env_config()

# 验证必需的配置项
required_keys = [
    "MEMGUI_STEP_DESC_MODEL",
    "MEMGUI_STEP_DESC_PROVIDER",
    "MEMGUI_STEP_DESC_BASE_URL",
    "MEMGUI_FINAL_DECISION_MODEL",
    "MEMGUI_FINAL_DECISION_PROVIDER",
    "MEMGUI_FINAL_DECISION_BASE_URL",
    "MEMGUI_API_KEY",
    "MEMGUI_MAX_RETRIES",
]

missing_keys = [key for key in required_keys if key not in _config]
if missing_keys:
    raise ValueError(
        f"Missing required MemGUI-Eval configuration keys: {missing_keys}"
    )

# 从config.yaml读取模型参数 - 不再提供默认值
# 最终决策模型配置
DEFAULT_MODEL = _config["MEMGUI_FINAL_DECISION_MODEL"]
DEFAULT_PROVIDER = _config["MEMGUI_FINAL_DECISION_PROVIDER"]
DEFAULT_API_URL = _config["MEMGUI_FINAL_DECISION_BASE_URL"]

# 步骤描述模型配置
DEFAULT_DESC_MODEL = _config["MEMGUI_STEP_DESC_MODEL"]
DEFAULT_DESC_PROVIDER = _config["MEMGUI_STEP_DESC_PROVIDER"]
DEFAULT_DESC_API_URL = _config["MEMGUI_STEP_DESC_BASE_URL"]

# max_tokens is intentionally not set - let the model use its default
DEFAULT_TEMPERATURE = 0.01

# 不再需要的参数
DEFAULT_APP_ID = None
DEFAULT_APP_KEY = None

# 从config.yaml读取重试参数
DEFAULT_MAX_RETRIES = _config["MEMGUI_MAX_RETRIES"]
DEFAULT_RETRY_DELAY = 2

# 模型配置字典，可以根据不同任务设置不同的参数
# Note: max_tokens is intentionally not included - let the model use its default
MODEL_CONFIGS = {
    "default": {
        "model": DEFAULT_MODEL,
        "provider": DEFAULT_PROVIDER,
        "temperature": DEFAULT_TEMPERATURE,
        "app_id": DEFAULT_APP_ID,
        "app_key": DEFAULT_APP_KEY,
        "api_url": DEFAULT_API_URL,
        "max_retries": DEFAULT_MAX_RETRIES,
        "retry_delay": DEFAULT_RETRY_DELAY,
    },
    "high_precision": {
        "model": DEFAULT_MODEL,
        "provider": DEFAULT_PROVIDER,
        "temperature": 0.01,  # Low temperature for more deterministic output
        "app_id": DEFAULT_APP_ID,
        "app_key": DEFAULT_APP_KEY,
        "api_url": DEFAULT_API_URL,
        "max_retries": DEFAULT_MAX_RETRIES,
        "retry_delay": DEFAULT_RETRY_DELAY,
    },
    "high_creativity": {
        "model": DEFAULT_MODEL,
        "provider": DEFAULT_PROVIDER,
        "temperature": 1.0,  # High temperature for more creative output
        "app_id": DEFAULT_APP_ID,
        "app_key": DEFAULT_APP_KEY,
        "api_url": DEFAULT_API_URL,
        "max_retries": DEFAULT_MAX_RETRIES,
        "retry_delay": DEFAULT_RETRY_DELAY,
    },
}


def get_model_config(config_name="default"):
    """
    获取指定名称的模型配置

    Args:
        config_name: 配置名称，默认为"default"

    Returns:
        配置字典
    """
    return MODEL_CONFIGS.get(config_name, MODEL_CONFIGS["default"])
