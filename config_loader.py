# encoding: utf-8
"""
Configuration Loader Module
Provides compatibility configuration loading for MemGUI-Eval.

This module handles:
1. Loading config.yaml when present
2. Applying user-facing .env overrides
3. Inheriting BASE_URL for MemGUI-Eval endpoints when specific endpoints are empty

Usage:
    from config_loader import load_config
    config = load_config()
"""

import os
import yaml
from dotenv import dotenv_values


def apply_eval_defaults(config, verbose=False):
    """Apply MemGUI-Eval defaults that are derived from user-facing values."""
    base_url = config.get("BASE_URL")

    url_fields = [
        "MEMGUI_STEP_DESC_BASE_URL",
        "MEMGUI_FINAL_DECISION_BASE_URL",
    ]
    for url_field in url_fields:
        if config.get(url_field) is None and base_url is not None:
            config[url_field] = base_url
    config.setdefault("MEMGUI_STEP_DESC_PROVIDER", "openai_compatible")
    config.setdefault("MEMGUI_FINAL_DECISION_PROVIDER", "openai_compatible")
    config.setdefault("MEMGUI_MAX_RETRIES", 4)

    if verbose:
        print("\n📊 Effective configuration:")
        print(f"   • BASE_URL: {config.get('BASE_URL')}")
        print(f"   • MEMGUI_STEP_DESC_MODEL: {config.get('MEMGUI_STEP_DESC_MODEL')}")
        print(f"   • MEMGUI_FINAL_DECISION_MODEL: {config.get('MEMGUI_FINAL_DECISION_MODEL')}")
        print()

    return config


def _normalize_env_value(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "none", "null"}:
        return None
    return value


def _apply_env_overrides(config, config_path=None):
    """
    Apply user-facing .env values on top of optional config.yaml defaults.
    """
    candidates = []
    if config_path:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(config_path)), ".env"))
    candidates.append(os.path.join(os.getcwd(), ".env"))

    env_path = next((path for path in candidates if os.path.exists(path)), None)
    file_values = dotenv_values(env_path) if env_path else {}
    values = {**file_values, **os.environ}

    direct_keys = [
        "BASE_URL",
        "MEMGUI_API_KEY",
        "MEMGUI_STEP_DESC_MODEL",
        "MEMGUI_STEP_DESC_PROVIDER",
        "MEMGUI_STEP_DESC_BASE_URL",
        "MEMGUI_FINAL_DECISION_MODEL",
        "MEMGUI_FINAL_DECISION_PROVIDER",
        "MEMGUI_FINAL_DECISION_BASE_URL",
        "MEMGUI_MAX_RETRIES",
    ]
    for key in direct_keys:
        if key in values:
            value = _normalize_env_value(values.get(key))
            if key == "MEMGUI_MAX_RETRIES" and value is not None:
                value = int(value)
            config[key] = value

    return config


def load_config(config_path=None, verbose=False):
    """
    Load configuration from YAML file with .env overrides applied.

    Args:
        config_path: Path to config.yaml. If None, auto-detects from project root.
        verbose: Whether to print configuration info

    Returns:
        Configuration dictionary with mode presets applied

    Raises:
        FileNotFoundError: If config.yaml is not found
        Exception: If there's an error loading the config
    """
    if config_path is None:
        # Try to find config.yaml in project root
        # First, try relative to this file
        this_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(this_dir, "config.yaml")

        if not os.path.exists(config_path):
            # Try current working directory
            config_path = os.path.join(os.getcwd(), "config.yaml")

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"config.yaml not found at {config_path}. "
            "Please ensure config.yaml exists in the project root."
        )

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except Exception as e:
        raise Exception(f"Error loading config.yaml: {e}")

    # Apply .env overrides before derived defaults so empty endpoint fields can
    # still inherit BASE_URL.
    config = _apply_env_overrides(config, config_path=config_path)

    config = apply_eval_defaults(config, verbose=verbose)

    return config


# Singleton pattern: cache the loaded config
_cached_config = None


def get_config(verbose=False):
    """
    Get the configuration, using cached version if available.

    This is useful for modules that need to access config without
    loading it multiple times.

    Args:
        verbose: Whether to print configuration info (only on first load)

    Returns:
        Configuration dictionary
    """
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config(verbose=verbose)
    return _cached_config


def reload_config(verbose=False):
    """
    Force reload the configuration from file.

    Use this if you need to pick up changes to config.yaml.

    Args:
        verbose: Whether to print configuration info

    Returns:
        Configuration dictionary
    """
    global _cached_config
    _cached_config = load_config(verbose=verbose)
    return _cached_config
