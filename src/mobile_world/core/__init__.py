"""Public MobileWorld-compatible core APIs for MemGUI-Bench.

The original MobileWorld package eagerly re-exported every API object here.
That makes lightweight commands such as ``mg env check`` import task registries,
agent implementations, MCP clients, and app helpers before they need them.  Keep
the public API shape, but resolve the exports lazily so environment management
stays fast and dependency-light.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "TaskInfo",
    "AgentInfo",
    "AppInfo",
    "MCPToolInfo",
    "TaskStatistics",
    "get_task_registry",
    "get_task_info",
    "list_tasks",
    "get_task_statistics",
    "list_agents",
    "get_agent_info",
    "list_apps",
    "get_app_info",
    "list_mcp_tools",
    "get_mcp_tool_info",
    "ContainerInfo",
    "ContainerConfig",
    "LaunchResult",
    "is_port_available",
    "find_available_ports",
    "find_next_container_index",
    "wait_for_container_ready",
    "build_container_config",
    "launch_container",
    "launch_containers",
    "list_containers",
    "get_container_info",
    "remove_container",
    "remove_containers",
    "restart_server_in_container",
    "resolve_container_name",
    "start_server",
    "create_server_config",
    "get_server_app",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        api = import_module("mobile_world.core.api")
        value = getattr(api, name)
        globals()[name] = value
        return value
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
