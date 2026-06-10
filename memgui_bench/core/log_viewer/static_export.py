"""Static HTML export for MemGUI-Bench trajectory sessions."""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import quote

from .data import load_session
from .render import render_index, render_task


def export_static_site(log_root: str | Path, output_dir: str | Path, overwrite: bool = False) -> None:
    root = Path(log_root).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if not (root / "results.csv").exists():
        raise FileNotFoundError(f"Not a MemGUI session directory: {root}")
    if output.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    files_dir = output / "files"
    shutil.copytree(root, files_dir)

    def rel_file_url(path: Path) -> str:
        rel = path.resolve().relative_to(root).as_posix()
        return "files/" + quote(rel)

    tasks_dir = output / "tasks"
    tasks_dir.mkdir()

    def task_filename(task_id: str, agent: str, attempt: int) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in f"{task_id}_{agent}_{attempt}")
        return f"tasks/{safe}.html"

    session = load_session(root)

    for task in session["tasks"]:
        for agent, attempts in task["attempts"].items():
            for attempt in attempts:
                if not attempt["has_log"] and attempt["status"] == "pending":
                    continue
                filename = task_filename(task["id"], agent, attempt["attempt"])
                html = render_task(
                    root,
                    task["id"],
                    agent,
                    attempt["attempt"],
                    file_url=rel_file_url,
                    index_url="../index.html",
                )
                (output / filename).write_text(html, encoding="utf-8")

    index = render_index(root, task_url=task_filename)
    (output / "index.html").write_text(index, encoding="utf-8")

