"""Log viewer module for MobileWorld trajectories.

This module provides a web-based viewer for trajectory logs using FastHTML.
The FastHTML app is loaded lazily so lightweight helpers such as
``mg logs results`` do not require web-viewer dependencies at import time.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["app", "main", "rt"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        module = import_module("mobile_world.core.log_viewer.app")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
