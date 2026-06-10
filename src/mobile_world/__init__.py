"""MemGUI-Bench runtime built on the MobileWorld architecture."""

from __future__ import annotations


def __getattr__(name: str):
    if name == "AndroidController":
        from mobile_world.runtime.controller import AndroidController

        return AndroidController
    raise AttributeError(name)

__all__ = ["AndroidController"]
