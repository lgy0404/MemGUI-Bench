from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memgui_bench.core.log_viewer.data import calculate_stats, load_session
from memgui_bench.core.log_viewer.render import render_index, render_task
from memgui_bench.core.log_viewer.static_export import export_static_site


def _write_fake_session(root: Path) -> Path:
    session = root / "session-smoke"
    attempt = session / "001-FindProductAndFilter" / "Qwen3VL" / "attempt_1"
    attempt.mkdir(parents=True)
    (session / "results.csv").write_text(
        "\n".join(
            [
                "task_identifier,task_description,task_app,requires_ui_memory,task_difficulty,golden_steps,Qwen3VL_successful_attempts,Qwen3VL_success_count,Qwen3VL_attempt_1_completion,Qwen3VL_attempt_1_total_steps,Qwen3VL_direct_with_action_attempt_1_evaluation",
                '001-FindProductAndFilter,"Find shoes","[\'Amazon\']",N,1,11,[1],1,Y,4,S',
            ]
        ),
        encoding="utf-8",
    )
    (attempt / "log.json").write_text(
        json.dumps(
            [
                {"step": 1, "action": ["click", {"detail_type": "coordinates", "detail": [100, 200]}]},
                {"total_steps": 1, "finish_signal": 1},
            ]
        ),
        encoding="utf-8",
    )
    (attempt / "evaluation_summary.json").write_text(
        json.dumps({"final_result": 1, "reason": "done"}),
        encoding="utf-8",
    )
    return session


class LogViewerTest(unittest.TestCase):
    def test_load_session_and_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _write_fake_session(Path(tmp))
            loaded = load_session(session)
            stats = calculate_stats(session)

            self.assertEqual(loaded["agents"], ["Qwen3VL"])
            self.assertEqual(loaded["tasks"][0]["best_status"], "success")
            self.assertEqual(stats["success"], 1)
            self.assertEqual(stats["success_rate"], 100.0)

    def test_render_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = _write_fake_session(Path(tmp))
            index_html = render_index(session, task_url=lambda task, agent, attempt: "/task")
            task_html = render_task(
                session,
                "001-FindProductAndFilter",
                "Qwen3VL",
                1,
                file_url=lambda path: path.name,
                index_url="/",
            )

            self.assertIn("001-FindProductAndFilter", index_html)
            self.assertIn("Qwen3VL", task_html)
            self.assertIn("done", task_html)

    def test_static_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = _write_fake_session(root)
            output = root / "site"
            export_static_site(session, output)

            self.assertTrue((output / "index.html").exists())
            self.assertTrue(any((output / "tasks").iterdir()))


if __name__ == "__main__":
    unittest.main()
