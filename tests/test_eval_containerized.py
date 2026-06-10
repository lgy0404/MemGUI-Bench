from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from memgui_bench.core.cli import create_parser
from memgui_bench.core.subcommands.eval import execute


class EvalContainerizedTest(unittest.TestCase):
    def test_parallel_eval_auto_launches_matching_container_count(self) -> None:
        parser = create_parser()
        args = parser.parse_args(
            [
                "eval",
                "--dry-run",
                "--num-emulators",
                "4",
                "--tasks",
                "001-A,002-B,003-C,004-D",
                "--session-id",
                "smoke",
            ]
        )

        output = io.StringIO()
        with (
            patch("memgui_bench.core.subcommands.eval._list_managed_containers", return_value=[]),
            patch("memgui_bench.core.subcommands.eval._next_container_index", return_value=0),
            patch("memgui_bench.core.subcommands.env._next_container_index", return_value=0),
            redirect_stdout(output),
        ):
            status = execute(args)

        text = output.getvalue()
        self.assertEqual(status, 0)
        self.assertEqual(text.count("docker run -d --privileged"), 4)
        self.assertIn("MemGUI backend run: 4 backend(s), 4 task(s)", text)
        self.assertEqual(text.count("POST <next-backend>/run_task"), 4)

    def test_parallel_eval_uses_one_emulator_per_container(self) -> None:
        parser = create_parser()
        args = parser.parse_args(
            [
                "eval",
                "--dry-run",
                "--num-emulators",
                "4",
                "--tasks",
                "001-A,002-B,003-C,004-D,005-E",
                "--session-id",
                "smoke",
                "--no-auto-env-run",
            ]
        )
        containers = [
            {
                "name": f"memgui_bench_env_{index}",
                "status": "Up 1 second",
                "image": "memgui",
                "backend_port": 6800 + index,
                "viewer_port": 8760 + index,
            }
            for index in range(4)
        ]

        output = io.StringIO()
        with (
            patch("memgui_bench.core.subcommands.eval._list_managed_containers", return_value=containers),
            redirect_stdout(output),
        ):
            status = execute(args)

        text = output.getvalue()
        self.assertEqual(status, 0)
        self.assertNotIn("docker exec", text)
        self.assertIn("dynamic task queue", text)
        self.assertIn("http://localhost:6800", text)
        self.assertIn("http://localhost:6803", text)
        self.assertIn("task=001-A", text)
        self.assertIn("task=005-E", text)

    def test_inside_container_forces_single_emulator(self) -> None:
        parser = create_parser()
        args = parser.parse_args(
            [
                "eval",
                "--dry-run",
                "--num-emulators",
                "4",
                "--tasks",
                "001-A",
                "--session-id",
                "smoke",
            ]
        )

        output = io.StringIO()
        with (
            patch("memgui_bench.core.subcommands.eval._inside_container", return_value=True),
            redirect_stdout(output),
        ):
            status = execute(args)

        text = output.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("forcing --num-emulators 1", text)
        self.assertIn("--num_emulators 1", text)
        self.assertNotIn("docker exec", text)


if __name__ == "__main__":
    unittest.main()
