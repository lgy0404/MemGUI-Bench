"""Small HTTP server for interactive MemGUI-Bench log viewing."""

from __future__ import annotations

import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .render import render_index, render_sessions, render_task


class LogViewerHandler(BaseHTTPRequestHandler):
    log_root: Path = Path(".")
    base_path: str = "/"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = html.encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_file(self, path: Path) -> None:
        try:
            path.resolve().relative_to(self.log_root.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN.value)
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.startswith("/files/"):
            rel = unquote(path[len("/files/") :])
            self._send_file(self.log_root / rel)
            return

        if path == "/task":
            task_id = query.get("task", [""])[0]
            agent = query.get("agent", [""])[0]
            try:
                attempt = int(query.get("attempt", ["1"])[0])
            except ValueError:
                attempt = 1
            self._send_html(
                render_task(
                    self.log_root,
                    task_id,
                    agent,
                    attempt,
                    file_url=lambda file_path: "/files/" + quote(file_path.resolve().relative_to(self.log_root.resolve()).as_posix()),
                    index_url="/",
                )
            )
            return

        if path != "/":
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return

        requested_root = query.get("log_root", [None])[0]
        if requested_root:
            candidate = Path(requested_root).expanduser().resolve()
            if (candidate / "results.csv").exists():
                type(self).log_root = candidate
                self.log_root = candidate

        if (self.log_root / "results.csv").exists():
            self._send_html(
                render_index(
                    self.log_root,
                    task_url=lambda task, agent, attempt: f"/task?task={quote(task)}&agent={quote(agent)}&attempt={attempt}",
                )
            )
        else:
            self._send_html(
                render_sessions(
                    self.log_root,
                    session_url=lambda session: "/?log_root=" + quote(str(session)),
                )
            )


def main(log_root: str = "", server_port: int = 8760, base_path: str = "/") -> None:
    root = Path(log_root or ".").expanduser().resolve()
    handler = type(
        "ConfiguredLogViewerHandler",
        (LogViewerHandler,),
        {"log_root": root, "base_path": base_path},
    )
    server = ThreadingHTTPServer(("0.0.0.0", server_port), handler)
    print(f"Link: http://localhost:{server_port}")
    print(f"Log root: {root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    import sys

    main(
        log_root=sys.argv[1] if len(sys.argv) > 1 else "",
        server_port=int(sys.argv[2]) if len(sys.argv) > 2 else 8760,
        base_path=sys.argv[3] if len(sys.argv) > 3 else "/",
    )
