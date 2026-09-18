import json
import tempfile
import unittest
from pathlib import Path

from job import JobExistsError, JobStatus, JobWorkspace


class DummyConfig:
    def __init__(self, root: Path):
        self.TEMP_DIR = str(root / "temp")
        self.OUTPUT_ROOT = str(root / "output")


class JobWorkspaceTests(unittest.TestCase):
    def test_two_jobs_use_different_intermediate_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = DummyConfig(Path(tmp))
            first = JobWorkspace.create(config, "贵阳市南明区", overwrite=False)
            second = JobWorkspace.create(config, "毕节市七星关区", overwrite=False)

            self.assertNotEqual(first.temp_dir, second.temp_dir)
            self.assertTrue(first.temp_dir.is_dir())
            self.assertTrue(second.temp_dir.is_dir())

    def test_existing_job_requires_overwrite_and_overwrite_only_cleans_target_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = DummyConfig(root)
            first = JobWorkspace.create(config, "任务一", overwrite=False)
            second = JobWorkspace.create(config, "任务二", overwrite=False)
            (first.temp_dir / "old.txt").write_text("old", encoding="utf-8")
            (first.output_dir / "old.mp4").write_text("old", encoding="utf-8")
            (second.temp_dir / "keep.txt").write_text("keep", encoding="utf-8")

            with self.assertRaises(JobExistsError):
                JobWorkspace.create(config, "任务一", overwrite=False)

            replaced = JobWorkspace.create(config, "任务一", overwrite=True)
            self.assertFalse((replaced.temp_dir / "old.txt").exists())
            self.assertFalse((replaced.output_dir / "old.mp4").exists())
            self.assertTrue((second.temp_dir / "keep.txt").exists())

    def test_rejects_path_traversal_job_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                JobWorkspace.create(DummyConfig(Path(tmp)), "../outside", overwrite=True)

    def test_status_records_completed_and_failed_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = JobWorkspace.create(DummyConfig(Path(tmp)), "状态测试", overwrite=False)
            status = JobStatus(workspace.status_path, "状态测试")
            status.start_step("tts")
            status.complete_step("tts")
            status.start_step("composite")
            status.fail_step("composite", RuntimeError("encoder failed"))

            payload = json.loads(workspace.status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["completed_steps"], ["tts"])
            self.assertEqual(payload["failed_step"], "composite")
            self.assertIn("encoder failed", payload["error"])


if __name__ == "__main__":
    unittest.main()
