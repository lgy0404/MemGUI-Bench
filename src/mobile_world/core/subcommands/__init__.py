"""Lazy subcommand exports for the MemGUI-Bench CLI."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "configure_server_parser": ("mobile_world.core.subcommands.server", "configure_parser"),
    "execute_server": ("mobile_world.core.subcommands.server", "execute"),
    "configure_eval_parser": ("mobile_world.core.subcommands.eval", "configure_parser"),
    "execute_eval": ("mobile_world.core.subcommands.eval", "execute"),
    "configure_test_parser": ("mobile_world.core.subcommands.test", "configure_parser"),
    "execute_test": ("mobile_world.core.subcommands.test", "execute"),
    "configure_device_parser": ("mobile_world.core.subcommands.device", "configure_parser"),
    "execute_device": ("mobile_world.core.subcommands.device", "execute"),
    "configure_logs_parser": ("mobile_world.core.subcommands.logs", "configure_parser"),
    "execute_logs": ("mobile_world.core.subcommands.logs", "execute"),
    "configure_env_parser": ("mobile_world.core.subcommands.env", "configure_parser"),
    "execute_env": ("mobile_world.core.subcommands.env", "execute"),
    "configure_info_parser": ("mobile_world.core.subcommands.info", "configure_parser"),
    "execute_info": ("mobile_world.core.subcommands.info", "execute"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
