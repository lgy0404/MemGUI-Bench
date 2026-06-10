"""Tests for converting MobileWorld trajectories to MemGUI-Eval workspaces."""

import json
from pathlib import Path

from mobile_world.runtime.utils.memgui_eval import prepare_memgui_eval_workspace


def test_prepare_memgui_eval_workspace_from_mobileworld_traj(tmp_path: Path):
    task_name = "001-FindProductAndFilter"
    task_dir = tmp_path / task_name
    screenshots_dir = task_dir / "screenshots"
    screenshots_dir.mkdir(parents=True)
    (screenshots_dir / f"{task_name}-0-1.png").write_bytes(b"fake")
    (task_dir / "traj.json").write_text(
        json.dumps(
            {
                "0": {
                    "traj": [
                        {
                            "step": 1,
                            "prediction": "tap search",
                            "action": {"action_type": "click", "x": 100, "y": 200},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    eval_root = prepare_memgui_eval_workspace(
        log_file_root=str(tmp_path),
        task_name=task_name,
        task_traj_dir=str(task_dir),
        agent_name="qwen3vl",
    )

    legacy_dir = eval_root / task_name / "qwen3vl" / "attempt_1"
    legacy_log = json.loads((legacy_dir / "log.json").read_text(encoding="utf-8"))

    assert (eval_root / "results.csv").exists()
    assert (legacy_dir / "0.png").exists()
    assert legacy_log[0]["action"] == [
        "click",
        {"detail_type": "coordinates", "detail": [100, 200]},
    ]
