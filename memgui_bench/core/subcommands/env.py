"""Environment subcommands for MemGUI-Bench."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memgui_bench.core.paths import project_root


DEFAULT_IMAGE = os.environ.get(
    "MEMGUI_BENCH_IMAGE",
    "crpi-6p9eo5da91i2tx5v.cn-hangzhou.personal.cr.aliyuncs.com/memgui/memgui-bench:26020301",
)
DEFAULT_NAME_PREFIX = "memgui_bench_env"
DEFAULT_WORKDIR = "/root/MemGUI-Bench"
DEFAULT_BACKEND_PORT = 6800
DEFAULT_VIEWER_PORT = 8760
DEFAULT_CONTAINER_RESULTS_DIR = f"{DEFAULT_WORKDIR}/results"
DEFAULT_CONTAINER_CONFIG_PATH = f"{DEFAULT_WORKDIR}/config.yaml"
DEFAULT_CONTAINER_ENV_PATH = f"{DEFAULT_WORKDIR}/.env"
CONTAINER_LABEL = "memgui.bench=1"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "env",
        help="Manage Docker environments for MemGUI-Bench",
    )
    env_subparsers = parser.add_subparsers(
        dest="env_command",
        help="Environment commands",
        required=True,
    )

    check = env_subparsers.add_parser(
        "check",
        help="Check Docker/KVM prerequisites and pull the MemGUI image",
    )
    check.add_argument("--json", dest="as_json", action="store_true", help="Print JSON output.")
    check.add_argument("--image", default=DEFAULT_IMAGE, help=f"Docker image to check (default: {DEFAULT_IMAGE}).")
    check.add_argument("--no-pull", action="store_true", help="Do not pull the image when it is missing.")

    run = env_subparsers.add_parser("run", help="Launch MemGUI-Bench container(s)")
    run.add_argument("--count", type=int, default=1, help="Number of containers to launch (default: 1).")
    run.add_argument("--name", help="Container name. Only valid when --count is 1.")
    run.add_argument(
        "--name-prefix",
        "--name_prefix",
        "--prefix",
        dest="name_prefix",
        default=DEFAULT_NAME_PREFIX,
        help=f"Container name prefix (default: {DEFAULT_NAME_PREFIX}).",
    )
    run.add_argument("--image", default=DEFAULT_IMAGE, help=f"Docker image to launch (default: {DEFAULT_IMAGE}).")
    run.add_argument("--workdir", default=DEFAULT_WORKDIR, help=f"Container working directory (default: {DEFAULT_WORKDIR}).")
    run.add_argument(
        "--results-dir",
        "--results_dir",
        dest="results_dir",
        default="./results",
        help="Host directory for trajectory logs and results (default: ./results).",
    )
    run.add_argument(
        "--container-results-dir",
        "--container_results_dir",
        dest="container_results_dir",
        default=DEFAULT_CONTAINER_RESULTS_DIR,
        help=f"Container results directory (default: {DEFAULT_CONTAINER_RESULTS_DIR}).",
    )
    run.add_argument(
        "--config",
        dest="config_path",
        default="./config.yaml",
        help="Host config.yaml to mount into the container when present (default: ./config.yaml).",
    )
    run.add_argument(
        "--env-file",
        "--env_file",
        dest="env_file",
        default="./.env",
        help="Host .env to mount into the container when present (default: ./.env).",
    )
    run.add_argument(
        "--no-config-mount",
        "--no_config_mount",
        dest="mount_config",
        action="store_false",
        default=True,
        help="Do not mount host config.yaml into the container.",
    )
    run.add_argument(
        "--no-env-mount",
        "--no_env_mount",
        dest="mount_env",
        action="store_false",
        default=True,
        help="Do not mount host .env into the container.",
    )
    run.add_argument(
        "--no-results-mount",
        "--no_results_mount",
        dest="mount_results",
        action="store_false",
        default=True,
        help="Do not mount the host results directory into the container.",
    )
    run.add_argument(
        "--backend-start-port",
        "--backend_start_port",
        dest="backend_start_port",
        type=int,
        default=DEFAULT_BACKEND_PORT,
        help=f"Starting host port for the MemGUI backend (default: {DEFAULT_BACKEND_PORT}).",
    )
    run.add_argument(
        "--viewer-start-port",
        "--viewer_start_port",
        dest="viewer_start_port",
        type=int,
        default=DEFAULT_VIEWER_PORT,
        help=f"Starting host port for the trajectory viewer (default: {DEFAULT_VIEWER_PORT}).",
    )
    run.add_argument(
        "--no-wait-ready",
        "--no_wait_ready",
        dest="wait_ready",
        action="store_false",
        default=True,
        help="Do not wait for backend /health to report ready after launch.",
    )
    run.add_argument(
        "--ready-timeout",
        "--ready_timeout",
        dest="ready_timeout",
        type=int,
        default=600,
        help="Seconds to wait for each backend to become ready (default: 600).",
    )
    run.add_argument("--pull", action="store_true", help="Pull the image before launching containers.")
    run.add_argument("--force", action="store_true", help="Remove an existing container with the same name first.")
    run.add_argument(
        "--launch-interval",
        "--launch_interval",
        dest="launch_interval",
        type=int,
        default=0,
        help="Seconds to wait between launching containers (default: 0).",
    )
    run.add_argument("--dry-run", "--dry_run", dest="dry_run", action="store_true", help="Print Docker commands without running them.")
    run.add_argument(
        "--command",
        "-c",
        dest="container_command",
        help="Command for the container. Defaults to starting the MemGUI backend server.",
    )

    list_cmd = env_subparsers.add_parser("list", help="List MemGUI-Bench containers")
    list_cmd.add_argument("--json", dest="as_json", action="store_true", help="Print JSON output.")

    rm = env_subparsers.add_parser("rm", help="Remove MemGUI-Bench containers")
    rm.add_argument("containers", nargs="*", help="Container names to remove. Defaults to MemGUI-managed containers.")
    rm.add_argument("--all", action="store_true", help="Remove all MemGUI-managed containers.")
    rm.add_argument("--force", "-f", action="store_true", help="Force remove running containers.")
    rm.add_argument("--dry-run", "--dry_run", dest="dry_run", action="store_true", help="Print Docker commands without running them.")

    exec_cmd = env_subparsers.add_parser("exec", help="Open a shell or run a command in a MemGUI container")
    exec_cmd.add_argument("container", nargs="?", help="Container name. Omit when exactly one MemGUI container exists.")
    exec_cmd.add_argument("--workdir", default=DEFAULT_WORKDIR, help=f"Container working directory (default: {DEFAULT_WORKDIR}).")
    exec_cmd.add_argument(
        "--command",
        "-c",
        dest="exec_command",
        help="Command to run inside the container. Defaults to an interactive bash shell.",
    )
    exec_cmd.add_argument("--dry-run", "--dry_run", dest="dry_run", action="store_true", help="Print Docker command without running it.")

    init = env_subparsers.add_parser("init", help="Create config.yaml and .env from the examples")
    init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite config.yaml and .env if they already exist.",
    )


def _run_capture(cmd: list[str], timeout: int | None = 10) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, output or f"exit code {result.returncode}"


def _run_quiet(cmd: list[str]) -> tuple[bool, str]:
    return _run_capture(cmd, timeout=10)


def _docker_image_exists(image: str) -> bool:
    ok, _ = _run_quiet(["docker", "image", "inspect", image])
    return ok


def _pull_image(image: str) -> tuple[bool, str]:
    print(f"Pulling Docker image: {image}")
    return _run_capture(["docker", "pull", image], timeout=None)


def _docker_command(cmd: list[str], dry_run: bool = False) -> int:
    if dry_run:
        print(" ".join(shlex_quote(part) for part in cmd))
        return 0
    return subprocess.run(cmd).returncode


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def _container_command(raw: str | None) -> list[str]:
    if raw:
        return ["bash", "-lc", raw]
    return ["uv", "run", "mg", "server", "--host", "0.0.0.0", "--port", str(DEFAULT_BACKEND_PORT)]


def _container_name(args: argparse.Namespace, index: int, start_index: int = 0) -> str:
    if args.name:
        return args.name
    return f"{args.name_prefix}_{start_index + index}"


def _resolve_host_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def _volume_args(args: argparse.Namespace, dry_run: bool) -> list[str]:
    volumes: list[tuple[Path, str]] = []
    if args.mount_results:
        results_dir = _resolve_host_path(args.results_dir)
        if not dry_run:
            results_dir.mkdir(parents=True, exist_ok=True)
        volumes.append((results_dir, args.container_results_dir))

    if args.mount_config:
        config_path = _resolve_host_path(args.config_path)
        if config_path.exists():
            volumes.append((config_path, DEFAULT_CONTAINER_CONFIG_PATH))
        elif not dry_run:
            print(f"Warning: {config_path} not found. Run `uv run mg env init` to create a host-mounted config.")

    if getattr(args, "mount_env", True):
        env_path = _resolve_host_path(args.env_file)
        if env_path.exists():
            volumes.append((env_path, DEFAULT_CONTAINER_ENV_PATH))
        elif not dry_run:
            print(f"Warning: {env_path} not found. Run `uv run mg env init` to create a host-mounted .env.")

    docker_args: list[str] = []
    for host_path, container_path in volumes:
        docker_args.extend(["-v", f"{host_path}:{container_path}"])
    return docker_args


def _is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            return True
    except OSError:
        return False


def _find_available_port_pairs(
    backend_start: int,
    viewer_start: int,
    count: int,
    dry_run: bool = False,
) -> list[tuple[int, int]]:
    if dry_run:
        return [(backend_start + index, viewer_start + index) for index in range(count)]

    pairs: list[tuple[int, int]] = []
    backend = backend_start
    viewer = viewer_start
    attempts = 0
    max_attempts = max(count * 1000, 1000)
    while len(pairs) < count and attempts < max_attempts:
        if _is_port_available(backend) and _is_port_available(viewer):
            pairs.append((backend, viewer))
        backend += 1
        viewer += 1
        attempts += 1
    return pairs


def _parse_ports(ports_text: str) -> dict[str, int | None]:
    ports = {"backend_port": None, "viewer_port": None}
    for mapping in ports_text.split(", "):
        if "->" not in mapping:
            continue
        host_part, container_part = mapping.split("->", 1)
        container_port = container_part.split("/")[0]
        try:
            host_port = int(host_part.rsplit(":", 1)[-1])
        except ValueError:
            continue
        if container_port == str(DEFAULT_BACKEND_PORT):
            ports["backend_port"] = host_port
        elif container_port == str(DEFAULT_VIEWER_PORT):
            ports["viewer_port"] = host_port
    return ports


def _wait_for_backend_ready(
    backend_port: int,
    timeout: int = 600,
    poll_interval: float = 2.0,
) -> bool:
    url = f"http://localhost:{backend_port}/health"
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and data.get("ok"):
                    return True
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(poll_interval)
    return False


def _list_managed_containers(running_only: bool = False) -> list[dict[str, Any]]:
    cmd = [
        "docker",
        "ps",
    ]
    if not running_only:
        cmd.append("-a")
    cmd.extend(
        [
            "--filter",
            f"label={CONTAINER_LABEL}",
            "--format",
            "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}",
        ]
    )
    ok, output = _run_capture(
        cmd,
        timeout=10,
    )
    if not ok or not output:
        return []
    containers = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            ports = _parse_ports(parts[3] if len(parts) >= 4 else "")
            containers.append(
                {
                    "name": parts[0],
                    "status": parts[1],
                    "image": parts[2],
                    **ports,
                }
            )
    return containers


def _resolve_container(name: str | None) -> tuple[str | None, str | None]:
    if name:
        return name, None
    containers = _list_managed_containers()
    if not containers:
        return None, "No MemGUI-Bench containers found. Run `uv run mg env run` first."
    if len(containers) > 1:
        names = ", ".join(container["name"] for container in containers)
        return None, f"Multiple MemGUI-Bench containers found ({names}). Please specify one."
    return containers[0]["name"], None


def _next_container_index(prefix: str) -> int:
    containers = _list_managed_containers()
    max_index = -1
    for container in containers:
        name = container["name"]
        if not name.startswith(f"{prefix}_"):
            continue
        suffix = name.removeprefix(f"{prefix}_")
        if suffix.isdigit():
            max_index = max(max_index, int(suffix))
    return max_index + 1


def _checks(args: argparse.Namespace) -> list[Check]:
    checks: list[Check] = []
    docker_path = shutil.which("docker")
    checks.append(Check("docker", bool(docker_path), str(docker_path or "not found")))

    docker_ok = False
    if docker_path:
        docker_ok, detail = _run_quiet(["docker", "version", "--format", "{{.Server.Version}}"])
        checks.append(Check("docker daemon", docker_ok, detail))

    kvm_path = Path("/dev/kvm")
    checks.append(Check("kvm", kvm_path.exists(), str(kvm_path)))

    example_path = project_root() / "config.yaml.example.opensource"
    checks.append(Check("config example", example_path.exists(), str(example_path)))

    env_example_path = project_root() / ".env.example"
    checks.append(Check("env example", env_example_path.exists(), str(env_example_path)))

    if docker_ok:
        image_exists = _docker_image_exists(args.image)
        if image_exists:
            checks.append(Check("docker image", True, args.image))
        elif args.no_pull:
            checks.append(Check("docker image", False, f"{args.image} not found"))
        else:
            ok, detail = _pull_image(args.image)
            checks.append(Check("docker image pull", ok, detail))
    else:
        checks.append(Check("docker image", False, "docker daemon unavailable"))

    return checks


def _print_checks(checks: list[Check]) -> None:
    width = max(len(check.name) for check in checks) if checks else 10
    print("MemGUI-Bench environment check")
    print("-" * 72)
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(f"{status:<5} {check.name:<{width}}  {check.detail}")
    print("-" * 72)
    failed = sum(1 for check in checks if not check.ok)
    print(f"{len(checks) - failed}/{len(checks)} checks passed")


def _execute_check(args: argparse.Namespace) -> int:
    checks = _checks(args)
    if args.as_json:
        print(json.dumps([check.__dict__ for check in checks], indent=2))
    else:
        _print_checks(checks)
    return 0 if all(check.ok for check in checks) else 1


def _execute_run(args: argparse.Namespace) -> int:
    if args.count < 1:
        print("Error: --count must be >= 1")
        return 1
    if args.name and args.count != 1:
        print("Error: --name can only be used with --count 1")
        return 1

    if args.pull and not args.dry_run:
        ok, detail = _pull_image(args.image)
        if not ok:
            print(f"Error: failed to pull image: {detail}")
            return 1

    command = _container_command(args.container_command)
    volume_args = _volume_args(args, args.dry_run)
    start_index = 0 if args.name else _next_container_index(args.name_prefix)
    port_pairs = _find_available_port_pairs(
        args.backend_start_port,
        args.viewer_start_port,
        args.count,
        dry_run=args.dry_run,
    )
    if len(port_pairs) < args.count:
        print(f"Error: only found {len(port_pairs)} available port pair(s) for {args.count} container(s).")
        return 1

    status = 0
    for index in range(args.count):
        name = _container_name(args, index, start_index)
        backend_port, viewer_port = port_pairs[index]
        if args.force:
            rm_cmd = ["docker", "rm", "-f", name]
            _docker_command(rm_cmd, dry_run=args.dry_run)
        docker_cmd = [
            "docker",
            "run",
            "-d",
            "--privileged",
            "--name",
            name,
            "--label",
            CONTAINER_LABEL,
            "-p",
            f"{backend_port}:{DEFAULT_BACKEND_PORT}",
            "-p",
            f"{viewer_port}:{DEFAULT_VIEWER_PORT}",
            *volume_args,
            "-w",
            args.workdir,
            args.image,
            *command,
        ]
        status = _docker_command(docker_cmd, dry_run=args.dry_run)
        if status != 0:
            return status
        if not args.dry_run:
            print(f"Launched {name} (backend: http://localhost:{backend_port}, viewer: {viewer_port})")
            if args.wait_ready:
                print(f"Waiting for {name} backend readiness...")
                if _wait_for_backend_ready(backend_port, timeout=args.ready_timeout):
                    print(f"{name} is ready")
                else:
                    print(f"Warning: {name} did not become ready within {args.ready_timeout}s")
        if args.launch_interval > 0 and index < args.count - 1 and not args.dry_run:
            time.sleep(args.launch_interval)
    return status


def _execute_list(args: argparse.Namespace) -> int:
    containers = _list_managed_containers()
    if args.as_json:
        print(json.dumps(containers, indent=2))
        return 0
    if not containers:
        print("No MemGUI-Bench containers found.")
        return 0
    width = max(len(container["name"]) for container in containers)
    print("MemGUI-Bench containers")
    print("-" * 72)
    for container in containers:
        backend = container.get("backend_port") or "-"
        viewer = container.get("viewer_port") or "-"
        print(
            f"{container['name']:<{width}}  {container['status']}  "
            f"backend={backend} viewer={viewer}  {container['image']}"
        )
    return 0


def _execute_rm(args: argparse.Namespace) -> int:
    names = list(args.containers)
    if args.all or not names:
        names = [container["name"] for container in _list_managed_containers()]
    if not names:
        print("No MemGUI-Bench containers found.")
        return 0
    cmd = ["docker", "rm"]
    if args.force:
        cmd.append("-f")
    cmd.extend(names)
    return _docker_command(cmd, dry_run=args.dry_run)


def _execute_exec(args: argparse.Namespace) -> int:
    name, error = _resolve_container(args.container)
    if error:
        print(f"Error: {error}")
        return 1
    assert name is not None

    interactive = args.exec_command is None
    cmd = ["docker", "exec"]
    if interactive and sys.stdin.isatty() and sys.stdout.isatty():
        cmd.append("-it")
    elif interactive:
        cmd.append("-i")
    cmd.extend(["-w", args.workdir, name])
    if args.exec_command:
        cmd.extend(["bash", "-lc", args.exec_command])
    else:
        cmd.append("bash")
    return _docker_command(cmd, dry_run=args.dry_run)


def _execute_init(args: argparse.Namespace) -> int:
    root = project_root()
    files = [
        (root / "config.yaml.example.opensource", root / "config.yaml"),
        (root / ".env.example", root / ".env"),
    ]
    for src, _ in files:
        if not src.exists():
            print(f"Error: example file not found: {src}")
            return 1

    for src, dst in files:
        if dst.exists() and not args.force:
            print(f"{dst.name} already exists, leaving unchanged: {dst}")
            continue
        shutil.copy2(src, dst)
        print(f"Created {dst}")
    return 0


def execute(args: argparse.Namespace) -> int:
    actions = {
        "check": _execute_check,
        "run": _execute_run,
        "list": _execute_list,
        "rm": _execute_rm,
        "exec": _execute_exec,
        "init": _execute_init,
    }
    handler = actions.get(args.env_command)
    if handler is None:
        print("Error: please specify an env subcommand.")
        return 1
    return handler(args)
