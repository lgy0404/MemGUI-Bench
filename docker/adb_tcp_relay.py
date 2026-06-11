#!/usr/bin/env python3
"""Small TCP relay used when socat is not available in the MemGUI base image."""

from __future__ import annotations

import argparse
import select
import socket
import threading


def relay(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [])
            for src in readable:
                dst = right if src is left else left
                data = src.recv(65536)
                if not data:
                    return
                dst.sendall(data)
    finally:
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()


def handle_client(client: socket.socket, target_host: str, target_port: int) -> None:
    try:
        target = socket.create_connection((target_host, target_port), timeout=10)
    except OSError:
        client.close()
        return
    relay(client, target)


def main() -> None:
    parser = argparse.ArgumentParser(description="TCP relay for ADB port forwarding")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=5556)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=5555)
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.listen_host, args.listen_port))
    server.listen()
    print(
        f"ADB relay listening on {args.listen_host}:{args.listen_port} "
        f"-> {args.target_host}:{args.target_port}",
        flush=True,
    )

    while True:
        client, _ = server.accept()
        thread = threading.Thread(
            target=handle_client,
            args=(client, args.target_host, args.target_port),
            daemon=True,
        )
        thread.start()
