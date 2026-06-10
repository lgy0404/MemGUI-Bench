"""Logs subcommand for MemGUI-Bench."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from memgui_bench.core.log_viewer.data import calculate_stats


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("logs", help="Work with MemGUI trajectory logs")
    logs_subparsers = parser.add_subparsers(dest="logs_command", help="Logs commands")

    view = logs_subparsers.add_parser("view", help="Launch interactive trajectory viewer")
    view.add_argument(
        "--log-dir",
        "--log_dir",
        dest="log_dir",
        required=True,
        help="Session directory or parent directory containing session-* folders.",
    )
    view.add_argument("--port", type=int, default=8760, help="Viewer port.")
    view.add_argument("--base", default="/", help="Reserved for MobileWorld-style deployment parity.")

    results = logs_subparsers.add_parser("results", help="Print a results summary table")
    results.add_argument("log_dirs", nargs="+", metavar="LOG_DIR")

    export = logs_subparsers.add_parser("export", help="Export logs as a static HTML site")
    export.add_argument("--log-dir", "--log_dir", dest="log_dir", required=True)
    export.add_argument("--output", "-o", required=True)
    export.add_argument("--overwrite", action="store_true")


def _execute_view(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "-m",
        "memgui_bench.core.log_viewer",
        args.log_dir,
        str(args.port),
        args.base,
    ]
    try:
        print("Starting MemGUI-Bench Log Viewer...")
        print(f"Log Root: {args.log_dir}")
        print(f"Open http://localhost:{args.port}")
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        print("\nShutting down log viewer...")
        return 0


def _print_results_table(log_dirs: list[str]) -> int:
    headers = ["Log Root", "Total", "Executed", "Success", "SR%", "Memory SR%", "Avg Steps", "Agents"]
    rows: list[list[str]] = []
    for log_dir in log_dirs:
        path = Path(log_dir).expanduser()
        if not path.exists():
            print(f"Warning: {path} does not exist, skipping.")
            continue
        stats = calculate_stats(path)
        rows.append(
            [
                path.name,
                str(stats["total"]),
                str(stats["executed"]),
                str(stats["success"]),
                f"{stats['success_rate']:.1f}",
                f"{stats['memory_success_rate']:.1f}",
                f"{stats['avg_steps']:.1f}",
                ",".join(stats["agents"]),
            ]
        )

    widths = [len(header) for header in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    print("  ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))
    return 0


def _execute_export(args: argparse.Namespace) -> int:
    from memgui_bench.core.log_viewer.static_export import export_static_site

    try:
        export_static_site(args.log_dir, args.output, overwrite=args.overwrite)
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Exported static viewer to {args.output}")
    return 0


def execute(args: argparse.Namespace) -> int:
    if args.logs_command == "view":
        return _execute_view(args)
    if args.logs_command == "results":
        return _print_results_table(args.log_dirs)
    if args.logs_command == "export":
        return _execute_export(args)
    print("Error: please specify a logs subcommand (view, results, export).")
    return 1

