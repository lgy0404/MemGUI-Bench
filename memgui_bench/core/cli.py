"""Command-line interface for MemGUI-Bench."""

from __future__ import annotations

import argparse
import sys

from memgui_bench import __version__

from . import subcommands


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memgui",
        description="MemGUI-Bench runner, environment checks, and trajectory viewer",
    )
    parser.add_argument("--version", action="version", version=f"memgui {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    subcommands.configure_env_parser(subparsers)
    subcommands.configure_eval_parser(subparsers)
    subcommands.configure_logs_parser(subparsers)
    subcommands.configure_info_parser(subparsers)
    subcommands.configure_server_parser(subparsers)
    return parser


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    if args.command in ("eval", "run"):
        raise SystemExit(subcommands.execute_eval(args))
    if args.command == "env":
        raise SystemExit(subcommands.execute_env(args))
    if args.command == "logs":
        raise SystemExit(subcommands.execute_logs(args))
    if args.command == "info":
        raise SystemExit(subcommands.execute_info(args))
    if args.command == "server":
        raise SystemExit(subcommands.execute_server(args))

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
