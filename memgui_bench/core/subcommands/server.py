"""Backend server for MemGUI-Bench Docker environments."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from memgui_bench.core.paths import project_root


class BackendState:
    """Shared state for the lightweight MemGUI backend."""

    def __init__(self) -> None:
        self.started_at = time.time()
        self.ready = False
        self.error: str | None = None
        self.devices: list[dict[str, Any]] = []
        self.current_task: str | None = None
        self._lock = threading.Lock()

    def mark_ready(self, devices: list[dict[str, Any]] | None = None) -> None:
        with self._lock:
            self.ready = True
            self.error = None
            self.devices = devices or []

    def mark_error(self, error: str) -> None:
        with self._lock:
            self.ready = False
            self.error = error

    def acquire_task(self, task: str) -> bool:
        with self._lock:
            if self.current_task is not None:
                return False
            self.current_task = task
            return True

    def release_task(self) -> None:
        with self._lock:
            self.current_task = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": self.ready and self.error is None,
                "ready": self.ready,
                "busy": self.current_task is not None,
                "current_task": self.current_task,
                "error": self.error,
                "devices": self.devices,
                "uptime_seconds": round(time.time() - self.started_at, 2),
            }


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "server",
        help="Run the MemGUI backend server inside a Docker environment",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0).")
    parser.add_argument("--port", type=int, default=6800, help="Port to bind (default: 6800).")
    parser.add_argument(
        "--prepare-device",
        "--prepare_device",
        dest="prepare_device",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Clone and boot one emulator before reporting ready (default: true).",
    )
    parser.add_argument(
        "--setup-avd",
        "--setup_avd",
        dest="setup_avd",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Clone the configured AVD before booting the emulator (default: true).",
    )


def _load_config(root: Path) -> dict[str, Any]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from config_loader import load_config

    return load_config(str(root / "config.yaml"), verbose=True)


def _prepare_device(state: BackendState, args: argparse.Namespace, root: Path) -> None:
    if not args.prepare_device:
        state.mark_ready([])
        return

    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from framework import utils

        config = _load_config(root)
        config["NUM_OF_EMULATOR"] = 1
        if args.setup_avd:
            utils.setup_avd(
                config["SYS_AVD_HOME"],
                os.path.join(str(root), config["SOURCE_AVD_HOME"]),
                config["SOURCE_AVD_NAME"],
                1,
                config["ANDROID_SDK_PATH"],
            )
        devices = utils.setup_emulator(
            config["EMULATOR_PATH"],
            config["SOURCE_AVD_NAME"],
            1,
        )
        state.mark_ready(devices)
    except Exception as exc:  # pragma: no cover - depends on Android runtime
        state.mark_error(str(exc))
        print(f"Failed to prepare MemGUI backend device: {exc}", file=sys.stderr)


def _append_option(cmd: list[str], flag: str, value: Any | None) -> None:
    if value is not None:
        cmd.extend([flag, str(value)])


def _build_runner_command(payload: dict[str, Any]) -> list[str]:
    task_ids = payload.get("task_ids") or []
    cmd = [
        sys.executable,
        "-m",
        "memgui_bench.core.cli",
        "eval",
        "--no-container",
        "--num-emulators",
        "1",
        "--no-concurrent",
    ]
    if payload.get("use_connected_devices", True):
        cmd.append("--use-connected-devices")

    _append_option(cmd, "--agents", payload.get("agents"))
    _append_option(cmd, "--mode", payload.get("mode"))
    _append_option(cmd, "--session-id", payload.get("session_id"))
    _append_option(cmd, "--max-attempts", payload.get("max_attempts"))
    _append_option(cmd, "--base-url", payload.get("base_url"))
    _append_option(cmd, "--api-key", payload.get("api_key"))
    _append_option(cmd, "--memgui-api-key", payload.get("memgui_api_key"))
    _append_option(cmd, "--model-name", payload.get("model_name"))
    _append_option(cmd, "--results-dir", payload.get("results_dir"))
    _append_option(cmd, "--dataset", payload.get("dataset"))
    _append_option(cmd, "--reasoning-mode", payload.get("reasoning_mode"))
    _append_option(cmd, "--action-mode", payload.get("action_mode"))

    if task_ids:
        cmd.extend(["--tasks", ",".join(str(task_id) for task_id in task_ids)])
    if payload.get("overwrite"):
        cmd.append("--overwrite")
    if payload.get("overwrite_session"):
        cmd.append("--overwrite-session")
    if payload.get("skip_key_components"):
        cmd.append("--skip-key-components")
    return cmd


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _make_handler(state: BackendState, root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MemGUIBackend/0.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            print(f"[{self.log_date_time_string()}] {format % args}")

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/health":
                snapshot = state.snapshot()
                _json_response(self, HTTPStatus.OK, snapshot)
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path.rstrip("/") != "/run_task":
                _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not found"})
                return

            snapshot = state.snapshot()
            if not snapshot["ok"]:
                _json_response(self, HTTPStatus.SERVICE_UNAVAILABLE, snapshot)
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            task_ids = payload.get("task_ids") or []
            task_label = ",".join(str(task_id) for task_id in task_ids) or "ALL"
            if not state.acquire_task(task_label):
                _json_response(self, HTTPStatus.CONFLICT, state.snapshot())
                return

            start_time = time.time()
            try:
                cmd = _build_runner_command(payload)
                print(f"Running task payload on backend: {' '.join(cmd)}", flush=True)
                env = os.environ.copy()
                devices = state.snapshot().get("devices") or []
                if devices:
                    env["MEMGUI_DEVICE_SERIAL"] = str(devices[0].get("serial", ""))
                completed = subprocess.run(cmd, cwd=root, env=env)
                body = {
                    "ok": completed.returncode == 0,
                    "returncode": completed.returncode,
                    "task_ids": task_ids,
                    "duration_seconds": round(time.time() - start_time, 2),
                }
                status = HTTPStatus.OK if completed.returncode == 0 else HTTPStatus.INTERNAL_SERVER_ERROR
                _json_response(self, status, body)
            finally:
                state.release_task()

    return Handler


def execute(args: argparse.Namespace) -> int:
    root = project_root()
    state = BackendState()
    prepare_thread = threading.Thread(
        target=_prepare_device,
        args=(state, args, root),
        daemon=True,
    )
    prepare_thread.start()

    server = ThreadingHTTPServer((args.host, args.port), _make_handler(state, root))
    print(f"MemGUI backend listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping MemGUI backend...", flush=True)
    finally:
        server.server_close()
    return 0
