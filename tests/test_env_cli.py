from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from memgui_bench.core.cli import create_parser
from memgui_bench.core.subcommands.env import _check_env_file, execute


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
                env_path = Path(tmp) / ".env"
                config_path.write_text("ENVIRONMENT_MODE: docker\n", encoding="utf-8")
                env_path.write_text("API_KEY=test\n", encoding="utf-8")
                args = parser.parse_args(["env", "run", "--dry-run"])

                output = io.StringIO()
                with redirect_stdout(output):
                    status = execute(args)
            finally:
                os.chdir(old_cwd)

        text = output.getvalue()
        self.assertEqual(status, 0)
        self.assertIn(f"{config_path}:/root/MemGUI-Bench/config.yaml", text)
        self.assertIn(f"{env_path}:/root/MemGUI-Bench/.env", text)

    def test_env_init_creates_env_file(self) -> None:
        parser = create_parser()
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                os.chdir(root)
                (root / "run.py").write_text("", encoding="utf-8")
                (root / "data").mkdir()
                (root / "config.yaml.example.opensource").write_text("ENVIRONMENT_MODE: docker\n", encoding="utf-8")
                (root / ".env.example").write_text("API_KEY=YOUR_API_KEY_HERE\n", encoding="utf-8")
                args = parser.parse_args(["env", "init"])

                output = io.StringIO()
                with redirect_stdout(output):
                    status = execute(args)

                self.assertEqual(status, 0)
                self.assertTrue((root / "config.yaml").exists())
                self.assertTrue((root / ".env").exists())
            finally:
                os.chdir(old_cwd)

    def test_env_check_requires_env_file(self) -> None:
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                check = _check_env_file()
            finally:
                os.chdir(old_cwd)

        self.assertFalse(check.ok)
        self.assertEqual(check.name, ".env Configuration")
        self.assertIn(".env file not found", check.detail)

    def test_env_check_accepts_valid_env_file(self) -> None:
        old_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                Path(".env").write_text(
                    "\n".join(
                        [
                            "BASE_URL=https://example.test/v1",
                            "API_KEY=agent-key",
                            "MEMGUI_API_KEY=eval-key",
                            "MEMGUI_STEP_DESC_MODEL=desc-model",
                            "MEMGUI_FINAL_DECISION_MODEL=judge-model",
                        ]
                    ),
                    encoding="utf-8",
                )
                check = _check_env_file()
            finally:
                os.chdir(old_cwd)

        self.assertTrue(check.ok)
        self.assertEqual(check.name, ".env Configuration")
        self.assertIn(".env file configured correctly", check.detail)


if __name__ == "__main__":
    unittest.main()
