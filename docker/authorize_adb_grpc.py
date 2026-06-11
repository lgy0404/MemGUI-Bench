#!/usr/bin/env python3
"""Accept the Android USB-debugging prompt through emulator gRPC."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import grpc


def _adb_devices() -> str:
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
    return result.stdout


def _is_device_authorized(device: str, adb_output: str) -> bool:
    for line in adb_output.splitlines():
        if line.startswith(f"{device}\t"):
            return "\tdevice" in line
    return False


def _is_device_unauthorized(device: str, adb_output: str) -> bool:
    for line in adb_output.splitlines():
        if line.startswith(f"{device}\t"):
            return "\tunauthorized" in line
    return False


def _tap(stub, touch_event_cls, touch_cls, x: int, y: int) -> None:
    stub.sendTouch(
        touch_event_cls(
            touches=[
                touch_cls(
                    x=x,
                    y=y,
                    identifier=1,
                    pressure=50,
                    touch_major=8,
                    touch_minor=8,
                )
            ]
        ),
        timeout=5,
    )
    time.sleep(0.08)
    stub.sendTouch(
        touch_event_cls(
            touches=[
                touch_cls(
                    x=x,
                    y=y,
                    identifier=1,
                    pressure=0,
                    touch_major=8,
                    touch_minor=8,
                )
            ]
        ),
        timeout=5,
    )


def _wait_for_authorized(device: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        output = _adb_devices()
        print(output.replace("\n", " | "), flush=True)
        if _is_device_authorized(device, output):
            return True
        time.sleep(1)
    return False


def _load_emulator_proto(proto_dir: Path):
    sys.path.insert(0, str(proto_dir))
    from emulator_controller_pb2 import ImageFormat, Touch, TouchEvent
    from emulator_controller_pb2_grpc import EmulatorControllerStub

    return EmulatorControllerStub, ImageFormat, Touch, TouchEvent


def authorize(args: argparse.Namespace) -> int:
    stub_cls, image_format_cls, touch_cls, touch_event_cls = _load_emulator_proto(args.proto_dir)
    stub = stub_cls(grpc.insecure_channel(f"127.0.0.1:{args.grpc_port}"))
    deadline = time.time() + args.timeout
    checkbox_tapped = False

    while time.time() < deadline:
        adb_output = _adb_devices()
        print(adb_output.replace("\n", " | "), flush=True)
        if _is_device_authorized(args.device, adb_output):
            print(f"ADB is already authorized for {args.device}", flush=True)
            return 0

        try:
            image = stub.getScreenshot(image_format_cls(format=image_format_cls.PNG), timeout=3)
        except grpc.RpcError as exc:
            print(f"Waiting for emulator gRPC: {exc.code().name}", flush=True)
            time.sleep(args.interval)
            continue

        if not image.image:
            print("Waiting for a non-empty emulator screenshot", flush=True)
            time.sleep(args.interval)
            continue

        if _is_device_unauthorized(args.device, adb_output):
            if args.tap_always_allow and not checkbox_tapped:
                _tap(stub, touch_event_cls, touch_cls, args.checkbox_x, args.checkbox_y)
                checkbox_tapped = True
                time.sleep(0.3)

            _tap(stub, touch_event_cls, touch_cls, args.allow_x, args.allow_y)
            print("Tapped Android USB-debugging authorization dialog", flush=True)

            if _wait_for_authorized(args.device, args.post_tap_timeout):
                print(f"ADB authorization accepted for {args.device}", flush=True)
                return 0

        time.sleep(args.interval)

    print(f"Timed out waiting for ADB authorization on {args.device}", file=sys.stderr, flush=True)
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument("--grpc-port", type=int, default=8554)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--interval", type=float, default=3)
    parser.add_argument("--post-tap-timeout", type=float, default=45)
    parser.add_argument("--proto-dir", type=Path, default=Path("/app/service/_emulator_proto"))
    parser.add_argument("--tap-always-allow", action="store_true", default=True)
    parser.add_argument("--checkbox-x", type=int, default=150)
    parser.add_argument("--checkbox-y", type=int, default=1295)
    parser.add_argument("--allow-x", type=int, default=900)
    parser.add_argument("--allow-y", type=int, default=1450)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(authorize(parse_args()))
