"""Subcommand registration helpers."""

from .env import configure_parser as configure_env_parser
from .env import execute as execute_env
from .eval import configure_parser as configure_eval_parser
from .eval import execute as execute_eval
from .info import configure_parser as configure_info_parser
from .info import execute as execute_info
from .logs import configure_parser as configure_logs_parser
from .logs import execute as execute_logs
from .server import configure_parser as configure_server_parser
from .server import execute as execute_server

__all__ = [
    "configure_env_parser",
    "configure_eval_parser",
    "configure_info_parser",
    "configure_logs_parser",
    "configure_server_parser",
    "execute_env",
    "execute_eval",
    "execute_info",
    "execute_logs",
    "execute_server",
]
