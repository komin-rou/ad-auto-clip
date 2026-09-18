import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main import parse_args, run_batch_command


class MainArgumentTests(unittest.TestCase):
    def test_accepts_location_facts_script_and_detection_overrides(self):
        args = parse_args([
            "--locations", "地区.xlsx", "--location-row", "3",
            "--facts", "facts.yaml", "--script", "测试文案",
            "--no-person-detection",
        ])
        self.assertEqual(args.locations, "地区.xlsx")
        self.assertEqual(args.location_row, 3)
        self.assertEqual(args.facts, "facts.yaml")
        self.assertEqual(args.script, "测试文案")
        self.assertTrue(args.no_person_detection)

    def test_accepts_resource_compatibility_batch_and_resume_commands(self):
        args = parse_args([
            "--scan-resources", "--jianying-compat-test", "--job", "测试地点",
            "--all-locations", "--resume", "--max-retries", "4",
        ])
        self.assertTrue(args.scan_resources)
        self.assertTrue(args.jianying_compat_test)
        self.assertTrue(args.all_locations)
        self.assertTrue(args.resume)
        self.assertEqual(args.max_retries, 4)

    def test_batch_command_loads_all_locations_and_writes_both_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = SimpleNamespace(
                LOCATIONS_FILE=str(root / "地区.xlsx"),
                OUTPUT_ROOT=str(root / "output"),
                TEMP_DIR=str(root / "temp"),
                BATCH_MAX_RETRIES=2,
                LOCATION_ROW=1,
            )
            args = SimpleNamespace(
                max_retries=3, resume=True, overwrite=False,
            )
            fake_report = SimpleNamespace(
                items=[SimpleNamespace(status="completed")],
                write_json=lambda path: Path(path),
                write_csv=lambda path: Path(path),
            )
            with patch("location_loader.load_locations", return_value=[object()]) as load, \
                 patch("batch_runner.run_batch", return_value=fake_report) as run:
                exit_code = run_batch_command(config, args, pipeline_factory=lambda row: object())

            self.assertEqual(exit_code, 0)
            load.assert_called_once_with(config.LOCATIONS_FILE)
            options = run.call_args.args[2]
            self.assertTrue(options.resume)
            self.assertEqual(options.max_retries, 3)


if __name__ == "__main__":
    unittest.main()
