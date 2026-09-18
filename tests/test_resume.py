import json
import tempfile
import unittest
from pathlib import Path

from config import AppConfig, config
from job import JobStatus, JobWorkspace, RunCheckpoint
from pipeline import VideoPipeline


class ResumeRecordingPipeline(VideoPipeline):
    def __init__(self, invalid_step=None):
        self.invalid_step = invalid_step
        self.calls = []

    def _run_named_step(self, name, ctx):
        self.calls.append(name)

    def _is_step_artifact_valid(self, name, ctx):
        return name != self.invalid_step


class ResumeTests(unittest.TestCase):
    def make_config(self, root: Path) -> AppConfig:
        path = root / "config.yaml"
        path.write_text(
            "\n".join([
                f'base_dir: "{str(root).replace(chr(92), chr(92) * 2)}"',
                'output_subdir: "测试任务"',
                'video_encoder: "libx264"',
            ]),
            encoding="utf-8",
        )
        return AppConfig.from_file(str(path), environ={})

    def test_loads_existing_workspace_status_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = self.make_config(Path(tmp))
            workspace = JobWorkspace.create(loaded, "续跑任务")
            status = JobStatus(workspace.status_path, workspace.name)
            status.start_step("tts")
            status.complete_step("tts")

            reopened = JobWorkspace.open_existing(loaded, "续跑任务")
            restored = JobStatus.load(reopened.status_path)

            self.assertEqual(restored.payload["completed_steps"], ["tts"])
            self.assertEqual(restored.payload["status"], "running")

    def test_checkpoint_round_trip_is_atomic_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.json"
            payload = {"tts_text": "测试", "completed": ["content", "tts"]}

            RunCheckpoint.save(payload, path)

            self.assertEqual(RunCheckpoint.load(path), payload)
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_resume_skips_valid_steps_and_restarts_from_first_invalid_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = self.make_config(Path(tmp))
            config.bind(loaded)
            first = ResumeRecordingPipeline()
            first.run("断点任务", skip_preflight=True)

            resumed = ResumeRecordingPipeline(invalid_step="subtitle")
            ctx = resumed.run("断点任务", resume=True, skip_preflight=True)

            steps = [name for name, _ in VideoPipeline.STEP_METHODS]
            self.assertEqual(resumed.calls, steps[steps.index("subtitle"):])
            payload = json.loads(ctx.workspace.status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["completed_steps"], steps)

    def test_resume_restarts_from_tts_when_tts_config_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = self.make_config(Path(tmp))
            config.bind(loaded)
            ResumeRecordingPipeline().run("配置变化", skip_preflight=True)

            loaded.TTS_RATE = "+10%"
            resumed = ResumeRecordingPipeline()
            resumed.run("配置变化", resume=True, skip_preflight=True)

            steps = [name for name, _ in VideoPipeline.STEP_METHODS]
            self.assertEqual(resumed.calls, steps[steps.index("tts"):])

    def test_resume_restarts_from_content_when_api_key_availability_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = self.make_config(Path(tmp))
            loaded.DEEPSEEK_API_KEY = ""
            config.bind(loaded)
            ResumeRecordingPipeline().run("接口变化", skip_preflight=True)

            loaded.DEEPSEEK_API_KEY = "now-configured"
            resumed = ResumeRecordingPipeline()
            resumed.run("接口变化", resume=True, skip_preflight=True)

            steps = [name for name, _ in VideoPipeline.STEP_METHODS]
            self.assertEqual(resumed.calls, steps)

    def test_resume_restarts_from_person_detection_when_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loaded = self.make_config(root)
            raw = Path(loaded.RAW_VIDEO_DIR)
            raw.mkdir(parents=True)
            clip = raw / "person.mp4"
            clip.write_bytes(b"first")
            config.bind(loaded)
            ResumeRecordingPipeline().run("素材变化", skip_preflight=True)

            clip.write_bytes(b"changed-content")
            resumed = ResumeRecordingPipeline()
            resumed.run("素材变化", resume=True, skip_preflight=True)

            steps = [name for name, _ in VideoPipeline.STEP_METHODS]
            self.assertEqual(resumed.calls, steps[steps.index("person_detection"):])


if __name__ == "__main__":
    unittest.main()
