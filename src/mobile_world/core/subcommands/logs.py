"""Logs subcommand for MemGUI-Bench CLI - Work with trajectory logs."""

import argparse
import os
import subprocess
import sys


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configure the logs subcommand parser."""
    logs_parser = subparsers.add_parser(
        "logs",
        help="Work with trajectory logs (view/analyze/export)",
    )

    logs_subparsers = logs_parser.add_subparsers(
        dest="logs_command",
        help="Logs commands",
    )

    # logs view - Interactive log viewing
    view_parser = logs_subparsers.add_parser(
        "view",
        help="Launch interactive log viewer",
    )
    view_parser.add_argument(
        "--log-dir",
        "--log_dir",
        dest="log_dir",
        required=True,
        help="Trajectory directory or parent directory containing trajectory dirs (e.g., traj_logs/logs_20251029_4 or traj_logs/)",
    )
    view_parser.add_argument(
        "--port",
        type=int,
        default=8760,
        help="Port for the viewer (default: 8760)",
    )
    view_parser.add_argument(
        "--base",
        type=str,
        default="/",
        help="Base path for deployment (default: /). Use '/site/' if deploying at /site/",
    )

    # logs results - Print results table
    results_parser = logs_subparsers.add_parser(
        "results",
        help="Print result summary tables for log directories",
    )
    results_parser.add_argument(
        "log_dirs",
        nargs="+",
        metavar="LOG_DIR",
        help="One or more log root directories to analyze",
    )

    # logs export - Export static site
    export_parser = logs_subparsers.add_parser(
        "export",
        help="Export logs as a static HTML site",
    )
    export_parser.add_argument(
        "--log-dir",
        "--log_dir",
        dest="log_dir",
        required=True,
        help="Root directory for log files",
    )
    export_parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output directory for the static site",
    )


def print_results_table(log_roots: list[str]) -> None:
    """Print results for multiple log roots as a table."""
    from rich.console import Console
    from rich.table import Table

    from mobile_world.core.log_viewer.utils import calculate_task_stats, read_log_metadata

    console = Console()

    memgui_rows = []
    default_rows = []
    memgui_table = Table(
        title="MemGUI Results Summary",
        show_header=True,
        header_style="bold cyan",
    )

    default_table = Table(title="Log Results Summary", show_header=True, header_style="bold cyan")
    default_table.add_column("Log Root", style="dim", no_wrap=True)
    default_table.add_column("Suite", style="magenta")
    default_table.add_column("Total", justify="right")
    default_table.add_column("Finished", justify="right")
    default_table.add_column("Success", justify="right")
    default_table.add_column("SR%", justify="right")
    default_table.add_column("Std SR%", justify="right")
    default_table.add_column("MCP SR%", justify="right")
    default_table.add_column("UI SR%", justify="right")
    default_table.add_column("UIQ", justify="right")
    default_table.add_column("Avg Steps", justify="right")
    default_table.add_column("Avg Queries", justify="right")
    default_table.add_column("Avg MCP", justify="right")

    for log_root in log_roots:
        if not os.path.exists(log_root):
            console.print(f"[yellow]Warning: {log_root} does not exist, skipping.[/yellow]")
            continue

        metadata = read_log_metadata(log_root)
        suite_family = metadata.get("suite_family", "memgui_bench")
        stats = calculate_task_stats(log_root, suite_family=suite_family)
        # Use basename for display, but show full path if duplicates exist
        display_name = os.path.basename(log_root.rstrip("/"))

        if suite_family == "memgui_bench":
            memgui_eval = stats.get("memgui_eval") or {}
            k = int(memgui_eval.get("max_attempt") or 1)
            memgui_rows.append(
                {
                    "display_name": display_name,
                    "stats": stats,
                    "memgui_eval": memgui_eval,
                    "max_attempt": k,
                }
            )
            continue

        default_rows.append(
            {
                "display_name": display_name,
                "suite_family": suite_family,
                "stats": stats,
            }
        )

    if memgui_rows:
        max_memgui_attempt = max(row["max_attempt"] for row in memgui_rows)
        memgui_table.add_column("Log Root", style="dim", no_wrap=True)
        memgui_table.add_column("Task Set", justify="right")
        memgui_table.add_column("Logged", justify="right")
        memgui_table.add_column("Evaluated", justify="right")
        memgui_table.add_column("Evaluating", justify="right")
        memgui_table.add_column("Awaiting Eval", justify="right")
        memgui_table.add_column("Running", justify="right")
        memgui_table.add_column("Infra", justify="right")
        memgui_table.add_column("Success", justify="right")
        memgui_table.add_column("Failed", justify="right")
        memgui_table.add_column("Avg Steps", justify="right")
        for attempt in range(1, max_memgui_attempt + 1):
            memgui_table.add_column(f"P@{attempt}%", justify="right")
        memgui_table.add_column("IRR%", justify="right")
        memgui_table.add_column("MTPR", justify="right")
        memgui_table.add_column("FRR%", justify="right")

        for row in memgui_rows:
            stats = row["stats"]
            memgui_eval = row["memgui_eval"]
            pass_rates = memgui_eval.get("pass_rates") or {}
            max_attempt = row["max_attempt"]
            pass_cells = [
                f"{pass_rates.get(attempt, 0.0):.1f}" if attempt <= max_attempt else "-"
                for attempt in range(1, max_memgui_attempt + 1)
            ]
            memgui_table.add_row(
                row["display_name"],
                str(stats["total_task_no"]),
                str(stats["total"]),
                str(memgui_eval.get("evaluated_count", stats["finished"])),
                str(stats.get("evaluating", 0)),
                str(stats.get("awaiting_eval", 0)),
                str(stats["running"]),
                str(stats.get("infra_failed", 0)),
                str(stats["success"]),
                str(stats["failed"]),
                f"{stats['avg_steps']:.1f}",
                *pass_cells,
                f"{memgui_eval.get('avg_irr', 0.0):.1f}",
                f"{memgui_eval.get('mtpr', 0.0):.3f}",
                f"{memgui_eval.get('frr', 0.0):.1f}",
            )
        console.print(memgui_table)

    for row in default_rows:
        stats = row["stats"]
        suite_family = row["suite_family"]
        default_table.add_row(
            row["display_name"],
            suite_family.replace("_", " ").title(),
            str(stats["total"]),
            str(stats["finished"]),
            str(stats["success"]),
            f"{stats['success_rate']:.1f}",
            f"{stats['standard_success_rate']:.1f}",
            f"{stats['mcp_success_rate']:.1f}",
            f"{stats['user_interaction_success_rate']:.1f}",
            f"{stats['uiq']:.3f}",
            f"{stats['avg_steps']:.1f}",
            f"{stats['avg_queries']:.2f}",
            f"{stats['avg_mcp_calls']:.2f}",
        )
    if default_rows:
        console.print(default_table)


async def execute(args: argparse.Namespace) -> None:
    """Execute the logs command."""
    if args.logs_command == "view":
        await _execute_view(args)
    elif args.logs_command == "results":
        _execute_results(args)
    elif args.logs_command == "export":
        _execute_export(args)
    else:
        print("❌ Error: Please specify a subcommand (view, results, export)")
        print("Run 'mg logs --help' for usage information.")
        sys.exit(1)


async def _execute_view(args: argparse.Namespace) -> None:
    """Execute the logs view command."""
    try:
        print("🚀 Starting MemGUI-Bench Trajectory Viewer...")
        print(f"📂 Log Root: {args.log_dir}")
        print(f"🌐 Opening web interface on port {args.port}...")

        # Build command arguments - run as module
        cmd = [
            sys.executable,
            "-m",
            "mobile_world.core.log_viewer",
            args.log_dir,
            str(args.port),
            args.base,
        ]

        # Run the script as a subprocess
        # This will block until the server is stopped (Ctrl+C)
        subprocess.run(cmd, check=True)

    except KeyboardInterrupt:
        print("\n👋 Shutting down log viewer...")
        sys.exit(0)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error starting log viewer: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error starting log viewer: {e}")
        sys.exit(1)


def _execute_results(args: argparse.Namespace) -> None:
    """Execute the logs results command."""
    print_results_table(args.log_dirs)


def _execute_export(args: argparse.Namespace) -> None:
    """Execute the logs export command."""
    from mobile_world.core.log_viewer.static_export import export_static_site

    if not os.path.exists(args.log_dir):
        print(f"❌ Error: Log directory does not exist: {args.log_dir}")
        sys.exit(1)

    export_static_site(args.log_dir, args.output)
