from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from memgui_bench.core.cli import create_parser
from memgui_bench.core.subcommands.env import execute


class EnvCliTest(unittest.TestCase):
    def test_env_run_dry_run_uses_detached_container(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["env", "run", "--dry-run", "--count", "2"])

        self.assertEqual(args.command, "env")
        self.assertEqual(args.env_command, "run")

        output = io.StringIO()
        with redirect_stdout(output):
            status = execute(args)

        text = output.getvalue()
        self.assertEqual(status, 0)
        self.assertIn("docker run -d --privileged", text)
        self.assertIn("-p 6800:6800", text)
        self.assertIn("-p 6801:6800", text)
        self.assertIn("-p 8760:8760", text)
        self.assertIn("-p 8761:8760", text)
        self.assertIn("uv run mg server --host 0.0.0.0 --port 6800", text)
        self.assertIn(":/root/MemGUI-Bench/results", text)
        self.assertNotIn("docker run -it", text)

    def test_env_exec_dry_run_keeps_top_level_command(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["env", "exec", "memgui_bench_env_0", "--dry-run"])

        self.assertEqual(args.command, "env")
        self.assertEqual(args.env_command, "exec")

        output = io.StringIO()
        with redirect_stdout(output):
            status = execute(args)

        self.assertEqual(status, 0)
        self.assertIn("docker exec", output.getvalue())

    def test_env_run_mounts_local_config_when_present(self) -> None:
        parser = create_parser()
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                config_path = Path(tmp) / "config.yaml"
                config_path.write_text("ENVIRONMENT_MODE: docker\n", encoding="utf-8")
                args = parser.parse_args(["env", "run", "--dry-run"])

                output = io.StringIO()
                with redirect_stdout(output):
                    status = execute(args)
            finally:
                os.chdir(old_cwd)

        text = output.getvalue()
        self.assertEqual(status, 0)
        self.assertIn(f"{config_path}:/root/MemGUI-Bench/config.yaml", text)


if __name__ == "__main__":
    unittest.main()
