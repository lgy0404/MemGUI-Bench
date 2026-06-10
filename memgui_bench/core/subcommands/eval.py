"""Eval subcommand for MemGUI-Bench."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from memgui_bench.core.paths import project_root
from memgui_bench.core.subcommands.env import (
    DEFAULT_BACKEND_PORT,
    DEFAULT_CONTAINER_RESULTS_DIR,
    DEFAULT_IMAGE,
    DEFAULT_NAME_PREFIX,
    DEFAULT_VIEWER_PORT,
    DEFAULT_WORKDIR,
    _execute_run as execute_env_run,
    _list_managed_containers,
    _next_container_index,
)


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "eval",
        aliases=["run"],
        help="Run MemGUI-Bench evaluation",
    )
    parser.add_argument(
        "--agent-type",
        "--agent_type",
        "--agents",
        dest="agents",
        help="Agent name(s), comma-separated. Defaults to AGENT_NAME in config.yaml.",
    )
    parser.add_argument(
        "--task",
        "--tasks",
        dest="tasks",
        default="ALL",
        help='Task id(s), comma-separated, or "ALL" for the configured dataset.',
    )
    parser.add_argument(
        "--mode",
        choices=["full", "exec", "eval"],
        default="full",
        help="Run execution+evaluation, execution only, or evaluation only.",
    )
    parser.add_argument(
        "--session-id",
        "--session_id",
        dest="session_id",
        help="Session identifier. Results go to results/session-<id>.",
    )
    parser.add_argument(
        "--max-attempts",
        "--max_attempts",
        dest="max_attempts",
        type=int,
        help="Maximum attempts per task.",
    )
    parser.add_argument("--model-name", "--model_name", dest="model_name", help="Agent model name.")
    parser.add_argument(
        "--llm-base-url",
        "--llm_base_url",
        "--base-url",
        "--base_url",
        dest="base_url",
        help="OpenAI-compatible base URL for agent and evaluator calls.",
    )
    parser.add_argument("--api-key", "--api_key", dest="api_key", help="Agent API key.")
    parser.add_argument(
        "--memgui-api-key",
        "--memgui_api_key",
        dest="memgui_api_key",
        help="Evaluator API key. Defaults to --api-key when omitted.",
    )
    parser.add_argument(
        "--num-emulators",
        "--num_emulators",
        dest="num_emulators",
        type=int,
        help="Number of MemGUI backend containers on the host; each backend runs one emulator.",
    )
    parser.add_argument(
        "--results-dir",
        "--results_dir",
        dest="results_dir",
        help="Override RESULTS_DIR for this run.",
    )
    parser.add_argument("--dataset", dest="dataset", help="Override DATASET_PATH for this run.")
    parser.add_argument(
        "--reasoning-mode",
        "--reasoning_mode",
        dest="reasoning_mode",
        choices=["result_only", "direct"],
        default=None,
        help="MemGUI-Eval reasoning mode.",
    )
    parser.add_argument(
        "--action-mode",
        "--action_mode",
        dest="action_mode",
        choices=["no_action", "with_action", "text_action"],
        default=None,
        help="MemGUI-Eval action evidence mode.",
    )
    parser.add_argument(
        "--max-concurrency",
        "--max_concurrency",
        dest="max_concurrency",
        type=int,
        help="Alias for --num-emulators in MemGUI-Bench.",
    )
    parser.add_argument(
        "--containerized",
        action="store_true",
        help="Run through MemGUI backend containers even when the backend count is 1.",
    )
    parser.add_argument(
        "--no-container",
        "--no_container",
        dest="no_container",
        action="store_true",
        help="Run in the current environment instead of backend containers.",
    )
    parser.add_argument(
        "--aw-host",
        "--aw_host",
        "--backend",
        "--backends",
        dest="backend_urls",
        help="Comma-separated MemGUI backend URL(s). Defaults to auto-discovery from containers.",
    )
    parser.add_argument(
        "--backend-start-port",
        "--backend_start_port",
        dest="backend_start_port",
        type=int,
        default=DEFAULT_BACKEND_PORT,
        help=f"Starting backend port for auto-launched containers (default: {DEFAULT_BACKEND_PORT}).",
    )
    parser.add_argument(
        "--viewer-start-port",
        "--viewer_start_port",
        dest="viewer_start_port",
        type=int,
        default=DEFAULT_VIEWER_PORT,
        help=f"Starting viewer port for auto-launched containers (default: {DEFAULT_VIEWER_PORT}).",
    )
    parser.add_argument(
        "--ready-timeout",
        "--ready_timeout",
        dest="ready_timeout",
        type=int,
        default=600,
        help="Seconds to wait for auto-launched backend readiness (default: 600).",
    )
    parser.add_argument(
        "--auto-retry",
        "--auto_retry",
        dest="auto_retry",
        type=int,
        default=0,
        help="Host-level retries for backend task failures (default: 0).",
    )
    parser.add_argument(
        "--env-image",
        "--env_image",
        dest="env_image",
        default=DEFAULT_IMAGE,
        help=f"MemGUI Docker image for containerized execution (default: {DEFAULT_IMAGE}).",
    )
    parser.add_argument(
        "--env-name-prefix",
        "--env_name_prefix",
        dest="env_name_prefix",
        default=DEFAULT_NAME_PREFIX,
        help=f"Container name prefix (default: {DEFAULT_NAME_PREFIX}).",
    )
    parser.add_argument(
        "--container-workdir",
        "--container_workdir",
        dest="container_workdir",
        default=DEFAULT_WORKDIR,
        help=f"Working directory inside MemGUI containers (default: {DEFAULT_WORKDIR}).",
    )
    parser.add_argument(
        "--container-results-dir",
        "--container_results_dir",
        dest="container_results_dir",
        default=DEFAULT_CONTAINER_RESULTS_DIR,
        help=f"Results directory inside MemGUI containers (default: {DEFAULT_CONTAINER_RESULTS_DIR}).",
    )
    parser.add_argument(
        "--launch-interval",
        "--launch_interval",
        dest="launch_interval",
        type=int,
        default=0,
        help="Seconds to wait between auto-launching missing containers.",
    )
    parser.add_argument(
        "--no-auto-env-run",
        "--no_auto_env_run",
        dest="auto_env_run",
        action="store_false",
        default=True,
        help="Do not auto-launch missing containers; fail if not enough are running.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing task results.")
    parser.add_argument(
        "--overwrite-session",
        "--overwrite_session",
        dest="overwrite_session",
        action="store_true",
        help="Prompt to clear an existing session directory before running.",
    )
    parser.add_argument(
        "--no-concurrent",
        "--no_concurrent",
        dest="no_concurrent",
        action="store_true",
        help="Disable multi-device parallel task execution.",
    )
    parser.add_argument(
        "--use-connected-devices",
        dest="use_connected_devices",
        action="store_true",
        help="Use currently connected ADB devices instead of cloning/launching AVDs.",
    )
    parser.add_argument(
        "--setup-emulator",
        "--setup_emulator",
        dest="setup_emulator",
        action="store_true",
        help="Launch configured emulators without cloning AVDs first.",
    )
    parser.add_argument(
        "--skip-key-components",
        "--skip_key_components",
        dest="skip_key_components",
        action="store_true",
        help="Forward the skip-key-components flag to the underlying runner.",
    )
    parser.add_argument(
        "--dry-run",
        "--dry_run",
        dest="dry_run",
        action="store_true",
        help="Print the underlying runner command(s) without executing.",
    )
    parser.add_argument(
        "--python",
        dest="python_executable",
        default=sys.executable,
        help="Python executable used by the benchmark runner.",
    )


def _split_tasks(tasks: str | None) -> list[str | None]:
    if not tasks or tasks.upper() == "ALL":
        return [None]
    return [task.strip() for task in tasks.split(",") if task.strip()]


def _split_task_ids(tasks: str | None) -> list[str]:
    if not tasks or tasks.upper() == "ALL":
        return []
    return [task.strip() for task in tasks.split(",") if task.strip()]


def _load_config(root: Path) -> dict:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from config_loader import load_config

    return load_config(str(root / "config.yaml"), verbose=False)


def _load_all_task_ids(args: argparse.Namespace, root: Path) -> list[str]:
    explicit = _split_task_ids(args.tasks)
    if explicit:
        return explicit

    config = _load_config(root)
    dataset = args.dataset or config.get("DATASET_PATH")
    if not dataset:
        raise RuntimeError("DATASET_PATH is not configured and --dataset was not provided.")
    dataset_path = Path(dataset)
    if not dataset_path.is_absolute():
        dataset_path = root / dataset_path
    if not dataset_path.exists():
        raise RuntimeError(f"Dataset not found: {dataset_path}")

    with dataset_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "task_identifier" not in (reader.fieldnames or []):
            raise RuntimeError(f"Dataset missing task_identifier column: {dataset_path}")
        return [row["task_identifier"] for row in reader if row.get("task_identifier")]


def _inside_container() -> bool:
    return os.environ.get("MEMGUI_CONTAINER_WORKER") == "1" or Path("/.dockerenv").exists()


def _requested_worker_count(args: argparse.Namespace, root: Path) -> int:
    if args.num_emulators is not None:
        return args.num_emulators
    if args.max_concurrency is not None:
        return args.max_concurrency
    try:
        return int(_load_config(root).get("NUM_OF_EMULATOR", 1))
    except Exception:
        return 1


def _should_use_container_executor(args: argparse.Namespace, root: Path) -> bool:
    if args.no_container or _inside_container() or args.mode == "eval":
        return False
    workers = _requested_worker_count(args, root)
    return args.containerized or workers >= 1


def _append_option(cmd: list[str], flag: str, value: object | None) -> None:
    if value is not None:
        cmd.extend([flag, str(value)])


def _build_base_command(args: argparse.Namespace, root: Path) -> list[str]:
    cmd = [args.python_executable, str(root / "run.py")]
    _append_option(cmd, "--agents", args.agents)
    _append_option(cmd, "--mode", args.mode)
    _append_option(cmd, "--session_id", args.session_id)
    _append_option(cmd, "--max_attempts", args.max_attempts)
    _append_option(cmd, "--base_url", args.base_url)
    _append_option(cmd, "--api_key", args.api_key)
    _append_option(cmd, "--memgui_api_key", args.memgui_api_key)
    _append_option(cmd, "--model_name", args.model_name)
    _append_option(cmd, "--num_emulators", args.num_emulators or args.max_concurrency)
    _append_option(cmd, "--results_dir", args.results_dir)
    _append_option(cmd, "--dataset", args.dataset)
    _append_option(cmd, "--reasoning_mode", args.reasoning_mode)
    _append_option(cmd, "--action_mode", args.action_mode)

    if args.overwrite:
        cmd.append("--overwrite")
    if args.overwrite_session:
        cmd.append("--overwrite_session")
    if args.no_concurrent:
        cmd.append("--no_concurrent")
    if args.use_connected_devices:
        cmd.append("--no-setup-avd")
    if args.setup_emulator:
        cmd.extend(["--no-setup-avd", "--setup_emulator"])
    if args.skip_key_components:
        cmd.extend(["--skip_key_components", "true"])
    return cmd


def _container_matches_prefix(container: dict[str, Any], prefix: str) -> bool:
    return container["name"].startswith(f"{prefix}_") or container["name"] == prefix


def _running_containers(prefix: str) -> list[dict[str, Any]]:
    containers = _list_managed_containers(running_only=True)
    return [container for container in containers if _container_matches_prefix(container, prefix)]


def _backend_url(port: int | str | None) -> str | None:
    if not port:
        return None
    return f"http://localhost:{port}"


def _backend_infos_from_urls(urls: list[str]) -> list[dict[str, Any]]:
    return [{"name": url, "backend_url": url} for url in urls]


def _parse_backend_urls(raw: str | None) -> list[str]:
    if not raw:
        return []
    urls = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if item.isdigit():
            item = f"http://localhost:{item}"
        elif not item.startswith(("http://", "https://")):
            item = f"http://{item}"
        urls.append(item.rstrip("/"))
    return urls


def _wait_for_backend_url_ready(url: str, timeout: int) -> bool:
    health_url = url.rstrip("/") + "/health"
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(health_url, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and data.get("ok"):
                    return True
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(2)
    return False


def _discover_backend_infos(args: argparse.Namespace) -> list[dict[str, Any]]:
    explicit = _parse_backend_urls(args.backend_urls)
    if explicit:
        return _backend_infos_from_urls(explicit)

    infos = []
    for container in _running_containers(args.env_name_prefix):
        url = _backend_url(container.get("backend_port"))
        if not url:
            continue
        infos.append({"name": container["name"], "backend_url": url})
    return infos


def _ensure_backends(args: argparse.Namespace, count: int, root: Path) -> list[dict[str, Any]]:
    backends = _discover_backend_infos(args)
    if len(backends) >= count:
        selected = backends[:count]
        if not args.dry_run:
            for backend in selected:
                if not _wait_for_backend_url_ready(backend["backend_url"], args.ready_timeout):
                    raise RuntimeError(f"Backend {backend['backend_url']} did not become ready.")
        return selected

    missing = count - len(backends)
    if args.backend_urls:
        raise RuntimeError(f"Need {count} backend URL(s), got {len(backends)} from --aw-host/--backend.")
    if not args.auto_env_run:
        names = ", ".join(backend["name"] for backend in backends) or "none"
        raise RuntimeError(
            f"Need {count} running MemGUI backend(s), found {len(backends)} ({names}). "
            "Run `sudo uv run mg env run --count <N>` first."
        )

    start_index = _next_container_index(args.env_name_prefix)
    launch_args = argparse.Namespace(
        count=missing,
        name=None,
        name_prefix=args.env_name_prefix,
        image=args.env_image,
        workdir=args.container_workdir,
        results_dir=args.results_dir or "./results",
        container_results_dir=args.container_results_dir,
        config_path=str(root / "config.yaml"),
        mount_config=True,
        mount_results=True,
        backend_start_port=args.backend_start_port + len(backends),
        viewer_start_port=args.viewer_start_port + len(backends),
        wait_ready=True,
        ready_timeout=args.ready_timeout,
        pull=False,
        force=False,
        launch_interval=args.launch_interval,
        dry_run=args.dry_run,
        container_command=None,
    )
    status = execute_env_run(launch_args)
    if status != 0:
        raise RuntimeError(f"Failed to launch {missing} MemGUI backend container(s).")

    if args.dry_run:
        planned = []
        for index in range(missing):
            planned.append(
                {
                    "name": f"{args.env_name_prefix}_{start_index + index}",
                    "backend_url": f"http://localhost:{launch_args.backend_start_port + index}",
                }
            )
        return backends + planned

    backends = _discover_backend_infos(args)
    if len(backends) < count:
        raise RuntimeError(f"Expected {count} running MemGUI backend(s), found {len(backends)}.")
    return backends[:count]


def _build_task_payload(args: argparse.Namespace, task_ids: list[str]) -> dict[str, Any]:
    return {
        "task_ids": task_ids,
        "agents": args.agents,
        "mode": args.mode,
        "session_id": args.session_id,
        "max_attempts": args.max_attempts,
        "base_url": args.base_url,
        "api_key": args.api_key,
        "memgui_api_key": args.memgui_api_key,
        "model_name": args.model_name,
        "results_dir": args.container_results_dir,
        "dataset": args.dataset,
        "reasoning_mode": args.reasoning_mode,
        "action_mode": args.action_mode,
        "overwrite": args.overwrite,
        "overwrite_session": args.overwrite_session,
        "skip_key_components": args.skip_key_components,
        "use_connected_devices": True,
    }


def _post_json(url: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def _run_task_on_backend(
    backend: dict[str, Any],
    args: argparse.Namespace,
    task_id: str,
) -> dict[str, Any]:
    url = backend["backend_url"].rstrip("/") + "/run_task"
    payload = _build_task_payload(args, [task_id])
    try:
        result = _post_json(url, payload, timeout=None)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "task_id": task_id,
            "backend": backend["name"],
            "error": f"HTTP {exc.code}: {detail}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "task_id": task_id,
            "backend": backend["name"],
            "error": str(exc),
        }

    return {
        "ok": bool(result.get("ok")),
        "task_id": task_id,
        "backend": backend["name"],
        "returncode": result.get("returncode"),
        "duration_seconds": result.get("duration_seconds"),
        "error": result.get("error"),
    }


def _execute_containerized(args: argparse.Namespace, root: Path) -> int:
    worker_count = max(1, _requested_worker_count(args, root))
    task_ids = _load_all_task_ids(args, root)
    if not task_ids:
        print("No tasks selected.")
        return 0

    backends = _ensure_backends(args, worker_count, root)

    print(
        f"MemGUI backend run: {len(backends)} backend(s), {len(task_ids)} task(s), "
        "dynamic task queue, 1 emulator per backend"
    )
    for backend in backends:
        print(f"  {backend['name']}: {backend['backend_url']}")

    if args.dry_run:
        print("Dry run. Requests that would be sent:")
        for task_id in task_ids:
            print(f"  POST <next-backend>/run_task task={task_id}")
        return 0

    task_queue: Queue[tuple[str, int]] = Queue()
    for task_id in task_ids:
        task_queue.put((task_id, 0))

    failed: list[dict[str, Any]] = []
    failed_lock = threading.Lock()

    def backend_worker(backend: dict[str, Any]) -> None:
        while True:
            try:
                task_id, attempt = task_queue.get_nowait()
            except Empty:
                return
            try:
                print(f"[{backend['name']}] Running {task_id}")
                result = _run_task_on_backend(backend, args, task_id)
                if result["ok"]:
                    print(
                        f"[{backend['name']}] Finished {task_id}"
                        + (
                            f" in {result['duration_seconds']}s"
                            if result.get("duration_seconds") is not None
                            else ""
                        )
                    )
                elif attempt < args.auto_retry:
                    print(
                        f"[{backend['name']}] Failed {task_id}; retrying "
                        f"({attempt + 1}/{args.auto_retry})"
                    )
                    task_queue.put((task_id, attempt + 1))
                else:
                    print(f"[{backend['name']}] Failed {task_id}: {result.get('error')}")
                    with failed_lock:
                        failed.append(result)
            finally:
                task_queue.task_done()

    with ThreadPoolExecutor(max_workers=len(backends)) as executor:
        futures = [executor.submit(backend_worker, backend) for backend in backends]
        for future in as_completed(futures):
            future.result()

    if failed:
        print(f"{len(failed)} task(s) failed:")
        for item in failed:
            print(f"  {item['task_id']} on {item['backend']}: {item.get('error')}")
        return 1
    return 0


def _display_command(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def execute(args: argparse.Namespace) -> int:
    root = project_root()
    if not (root / "run.py").exists():
        print(f"Error: run.py not found under {root}")
        return 1

    if args.api_key and not args.memgui_api_key:
        args.memgui_api_key = args.api_key

    if _inside_container() and args.mode in ("full", "exec"):
        requested = args.num_emulators or args.max_concurrency
        if requested and requested != 1:
            print(
                "MemGUI container worker detected; forcing --num-emulators 1. "
                "Use host-side `mg eval --num-emulators N` for N-way backend parallelism."
            )
        args.num_emulators = 1
        args.max_concurrency = None

    if _should_use_container_executor(args, root):
        try:
            return _execute_containerized(args, root)
        except Exception as exc:
            print(f"Error: {exc}")
            return 1

    commands = []
    for task_id in _split_tasks(args.tasks):
        cmd = _build_base_command(args, root)
        if task_id:
            cmd.extend(["--task_id", task_id])
        commands.append(cmd)

    if args.dry_run:
        print("Dry run. Commands that would be executed:")
        for cmd in commands:
            print(f"  {_display_command(cmd)}")
        return 0

    env = os.environ.copy()
    status = 0
    for idx, cmd in enumerate(commands, start=1):
        if len(commands) > 1:
            print(f"\n[{idx}/{len(commands)}] Running task command: {_display_command(cmd)}")
        completed = subprocess.run(cmd, cwd=root, env=env)
        if completed.returncode != 0:
            status = completed.returncode
            break
    return status
