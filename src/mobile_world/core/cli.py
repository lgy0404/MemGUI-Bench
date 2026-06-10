"""Command-line interface for MemGUI-Bench on the MobileWorld framework."""

import argparse
import asyncio
import sys

from . import subcommands


_COMMAND_CONFIGURERS = {
    "server": "configure_server_parser",
    "eval": "configure_eval_parser",
    "run": "configure_eval_parser",
    "test": "configure_test_parser",
    "device": "configure_device_parser",
    "viewer": "configure_device_parser",
    "logs": "configure_logs_parser",
    "env": "configure_env_parser",
    "info": "configure_info_parser",
}


def create_parser(selected_command: str | None = None) -> argparse.ArgumentParser:
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="mg",
        description="MemGUI-Bench runner, environment manager, and trajectory viewer",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    if selected_command in _COMMAND_CONFIGURERS:
        getattr(subcommands, _COMMAND_CONFIGURERS[selected_command])(subparsers)
    else:
        # Configure all subcommand parsers for root help, unknown commands, and
        # programmatic callers that expect the full parser tree.
        configured: set[str] = set()
        for configure_name in _COMMAND_CONFIGURERS.values():
            if configure_name in configured:
                continue
            configure = getattr(subcommands, configure_name)
            configure(subparsers)
            configured.add(configure_name)

    return parser


async def async_main() -> None:
    """Main CLI entry point."""
    selected_command = None
    if len(sys.argv) > 1 and sys.argv[1] not in {"-h", "--help"}:
        selected_command = sys.argv[1]
    parser = create_parser(selected_command)
    args = parser.parse_args()

    if args.command == "server":
        await subcommands.execute_server(args)
    elif args.command in ("eval", "run"):
        await subcommands.execute_eval(args)
    elif args.command == "test":
        await subcommands.execute_test(args)
    elif args.command in ("device", "viewer"):
        await subcommands.execute_device(args)
    elif args.command == "logs":
        await subcommands.execute_logs(args)
    elif args.command == "env":
        await subcommands.execute_env(args)
    elif args.command == "info":
        await subcommands.execute_info(args)
    else:
        parser.print_help()
        sys.exit(1)


def main():
    asyncio.run(async_main())
