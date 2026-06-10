"""Lazy public APIs for MobileWorld-compatible core functionality."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "DEFAULT_IMAGE": "mobile_world.core.api.env",
    "DEFAULT_NAME_PREFIX": "mobile_world.core.api.env",
    "ContainerConfig": "mobile_world.core.api.env",
    "ContainerInfo": "mobile_world.core.api.env",
    "LaunchResult": "mobile_world.core.api.env",
    "build_container_config": "mobile_world.core.api.env",
    "find_available_ports": "mobile_world.core.api.env",
    "find_next_container_index": "mobile_world.core.api.env",
    "get_container_info": "mobile_world.core.api.env",
    "is_port_available": "mobile_world.core.api.env",
    "launch_container": "mobile_world.core.api.env",
    "launch_containers": "mobile_world.core.api.env",
    "list_containers": "mobile_world.core.api.env",
    "remove_container": "mobile_world.core.api.env",
    "remove_containers": "mobile_world.core.api.env",
    "resolve_container_name": "mobile_world.core.api.env",
    "restart_server_in_container": "mobile_world.core.api.env",
    "wait_for_container_ready": "mobile_world.core.api.env",
    "TaskInfo": "mobile_world.core.api.info",
    "AgentInfo": "mobile_world.core.api.info",
    "AppInfo": "mobile_world.core.api.info",
    "MCPToolInfo": "mobile_world.core.api.info",
    "TaskStatistics": "mobile_world.core.api.info",
    "get_agent_info": "mobile_world.core.api.info",
    "get_app_info": "mobile_world.core.api.info",
    "get_mcp_tool_info": "mobile_world.core.api.info",
    "get_task_info": "mobile_world.core.api.info",
    "get_task_registry": "mobile_world.core.api.info",
    "get_task_statistics": "mobile_world.core.api.info",
    "list_agents": "mobile_world.core.api.info",
    "list_apps": "mobile_world.core.api.info",
    "list_mcp_tools": "mobile_world.core.api.info",
    "list_tasks": "mobile_world.core.api.info",
    "create_server_config": "mobile_world.core.api.server",
    "get_server_app": "mobile_world.core.api.server",
    "start_server": "mobile_world.core.api.server",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
