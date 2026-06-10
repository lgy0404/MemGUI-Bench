from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_loader import load_config


class ConfigLoaderTest(unittest.TestCase):
    def test_env_file_overrides_user_facing_model_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text(
                """
ENVIRONMENT_MODE: "docker"
BASE_URL: null
OPENAI_API_KEY: null
QWEN_API_KEY: null
QWEN_MODEL: "qwen/qwen3-vl-8b-instruct"
MEMGUI_API_KEY: null
MEMGUI_STEP_DESC_MODEL: "google/gemini-2.5-flash"
MEMGUI_STEP_DESC_BASE_URL: null
MEMGUI_FINAL_DECISION_MODEL: "google/gemini-2.5-pro"
MEMGUI_FINAL_DECISION_BASE_URL: null
SESSION_ID_SUFFIX: "debug"
NUM_OF_EMULATOR: 4
MAX_EVAL_SUBPROCESS: 8
_MODE_PRESETS:
  environment:
    docker: {}
  run:
    _MAX_ATTEMPTS: 3
    _RESULTS_DIR: "./results"
    _SESSION_PREFIX: "memgui-"
""",
                encoding="utf-8",
            )
            (root / ".env").write_text(
                "\n".join(
                    [
                        "BASE_URL=https://example.test/v1",
                        "API_KEY=agent-key",
                        "MEMGUI_API_KEY=eval-key",
                        "MEMGUI_STEP_DESC_MODEL=desc-model",
                        "MEMGUI_STEP_DESC_BASE_URL=",
                        "MEMGUI_FINAL_DECISION_MODEL=judge-model",
                        "MEMGUI_FINAL_DECISION_BASE_URL=",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = load_config(str(config_path), verbose=False)

        self.assertEqual(config["BASE_URL"], "https://example.test/v1")
        self.assertEqual(config["OPENAI_API_KEY"], "agent-key")
        self.assertEqual(config["QWEN_API_KEY"], "agent-key")
        self.assertEqual(config["MEMGUI_API_KEY"], "eval-key")
        self.assertEqual(config["MEMGUI_STEP_DESC_MODEL"], "desc-model")
        self.assertEqual(config["MEMGUI_STEP_DESC_BASE_URL"], "https://example.test/v1")
        self.assertEqual(config["MEMGUI_FINAL_DECISION_MODEL"], "judge-model")
        self.assertEqual(config["MEMGUI_FINAL_DECISION_BASE_URL"], "https://example.test/v1")


if __name__ == "__main__":
    unittest.main()
