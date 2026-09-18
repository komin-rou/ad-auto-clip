import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


YAML_TEXT = """\
base_dir: "{base_dir}"
output_subdir: "测试任务"
video_encoder: "libx264"
sticker_count: 2
deepseek_api_key: ""
"""


class ConfigTests(unittest.TestCase):
    def test_relative_paths_are_resolved_from_config_directory(self):
        from config import AppConfig

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "portable-project"
            project.mkdir()
            config_path = project / "config.yaml"
            config_path.write_text(
                'base_dir: "."\nlocations_file: "data/locations.xlsx"\n'
                'facts_file: "facts.yaml"\nvideo_encoder: "libx264"\n',
                encoding="utf-8",
            )

            previous = Path.cwd()
            os.chdir(root)
            try:
                loaded = AppConfig.from_file(str(config_path), environ={})
            finally:
                os.chdir(previous)

            self.assertEqual(Path(loaded.BASE_DIR), project.resolve())
            self.assertEqual(
                Path(loaded.LOCATIONS_FILE),
                (project / "data" / "locations.xlsx").resolve(),
            )
            self.assertEqual(Path(loaded.FACTS_FILE), (project / "facts.yaml").resolve())

    def test_content_aware_defaults_are_valid_and_person_speed_is_bounded(self):
        from config import AppConfig

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text(
                YAML_TEXT.format(base_dir=str(root).replace("\\", "\\\\"))
                + 'preferred_speed: 2.0\nminimum_speed: 1.0\n',
                encoding="utf-8",
            )
            loaded = AppConfig.from_file(str(config_path), environ={})
            self.assertEqual(loaded.PREFERRED_SPEED, 2.0)
            self.assertEqual(loaded.MINIMUM_SPEED, 1.0)
            self.assertTrue(loaded.LOCATIONS_FILE.endswith("地区.xlsx"))
            self.assertTrue(loaded.JIANYING_DRAFT_ENABLED)
            self.assertEqual(loaded.JIANYING_DRAFT_NAME, "editable")
    def test_import_does_not_run_subprocess_or_create_runtime_directories(self):
        sys.modules.pop("config", None)
        with patch("subprocess.run", side_effect=AssertionError("import ran subprocess")):
            module = importlib.import_module("config")
        self.assertFalse(module.config.is_bound)

    def test_from_file_loads_secret_from_environment_without_mutating_process_environment(self):
        from config import AppConfig

        original_process_value = os.environ.get("DEEPSEEK_API_KEY")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text(
                YAML_TEXT.format(base_dir=str(root).replace("\\", "\\\\")),
                encoding="utf-8",
            )
            environ = {"DEEPSEEK_API_KEY": "test-secret"}

            loaded = AppConfig.from_file(str(config_path), environ=environ)

            self.assertEqual(loaded.DEEPSEEK_API_KEY, "test-secret")
            self.assertEqual(loaded.BASE_DIR, str(root))
            self.assertEqual(loaded.STICKER_COUNT, 2)
            self.assertEqual(os.environ.get("DEEPSEEK_API_KEY"), original_process_value)

    def test_dotenv_value_is_used_when_process_environment_is_missing(self):
        from config import AppConfig

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text(
                YAML_TEXT.format(base_dir=str(root).replace("\\", "\\\\")),
                encoding="utf-8",
            )
            (root / ".env").write_text("DEEPSEEK_API_KEY=dotenv-secret\n", encoding="utf-8")

            loaded = AppConfig.from_file(str(config_path), environ={})

            self.assertEqual(loaded.DEEPSEEK_API_KEY, "dotenv-secret")


if __name__ == "__main__":
    unittest.main()
