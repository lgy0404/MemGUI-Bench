"""Path helpers shared by the MemGUI-Bench CLI."""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return the repository root for an editable/source checkout."""
    cwd = Path.cwd()
    if (cwd / "run.py").exists() and (cwd / "data").exists():
        return cwd
    return Path(__file__).resolve().parents[2]


def resolve_from_root(path: str | Path) -> Path:
    """Resolve a user path relative to the repository root."""
    path = Path(path).expanduser()
    if path.is_absolute():
        return path
    return project_root() / path


def session_dir_from_id(session_id: str, results_dir: str | Path = "./results") -> Path:
    """Resolve a MemGUI session id to its results directory."""
    session_id = session_id.removeprefix("session-")
    return resolve_from_root(results_dir) / f"session-{session_id}"

