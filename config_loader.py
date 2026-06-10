# encoding: utf-8
"""
Configuration Loader Module
Provides unified configuration loading with mode-based presets support.

This module handles:
1. Loading config.yaml
2. Applying user-facing .env overrides
3. Applying fixed environment presets (ENVIRONMENT_MODE)

Usage:
    from config_loader import load_config
    config = load_config()
"""

import os
import yaml
from dotenv import dotenv_values


def apply_mode_presets(config, verbose=False):
    """
    Apply mode-based presets to configuration.

    Mode precedence: .env overrides > mode presets > default values

    Supported modes:
    - ENVIRONMENT_MODE: "docker" (uses the preconfigured benchmark container)

    Args:
        config: Raw configuration dictionary loaded from YAML
        verbose: Whether to print configuration info

    Returns:
        Processed configuration dictionary with presets applied
    """
    presets = config.get("_MODE_PRESETS", {})

    # Get current mode selections
    environment_mode = config.get("ENVIRONMENT_MODE", "docker")

    if verbose:
        print("📋 Loading configuration with modes:")
        print(f"   • Environment: {environment_mode}")

    # Define mapping from preset keys to config keys
    preset_to_config = {
        "_ADB_PATH": "ADB_PATH",
        "_EMULATOR_PATH": "EMULATOR_PATH",
        "_ANDROID_SDK_PATH": "ANDROID_SDK_PATH",
        "_DEFAULT_KEYBOARD_PACKAGE": "DEFAULT_KEYBOARD_PACKAGE",
        "_SYS_AVD_HOME": "SYS_AVD_HOME",
        "_SOURCE_AVD_HOME": "SOURCE_AVD_HOME",
    }

    # Get BASE_URL from config (user-defined, no default to avoid leakage)
    base_url = config.get("BASE_URL")

    # Apply BASE_URL to all URL fields if they are null (only when base_url is set)
    url_fields = [
        "MEMGUI_STEP_DESC_BASE_URL",
        "MEMGUI_FINAL_DECISION_BASE_URL",
    ]
    for url_field in url_fields:
        if config.get(url_field) is None and base_url is not None:
            config[url_field] = base_url

    # Apply environment mode presets
    env_presets = presets.get("environment", {}).get(environment_mode, {})
    for preset_key, config_key in preset_to_config.items():
        if preset_key in env_presets and config_key:
            preset_value = env_presets[preset_key]
            if config.get(config_key) is None:
                config[config_key] = preset_value

    if verbose:
        print("\n📊 Effective configuration:")
        print(f"   • BASE_URL: {config.get('BASE_URL')}")
        print(f"   • DATASET_PATH: {config.get('DATASET_PATH')}")
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
    Apply user-facing .env values on top of config.yaml defaults.

    config.yaml keeps benchmark defaults and paths; .env contains the small set
    of values users normally edit, matching the MobileWorld setup style.
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
    Load configuration from YAML file with mode presets applied.

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

    # Apply .env overrides before presets so null values can still inherit defaults.
    config = _apply_env_overrides(config, config_path=config_path)

    # Apply mode-based presets
    config = apply_mode_presets(config, verbose=verbose)

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
