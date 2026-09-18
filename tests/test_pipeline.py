import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config import AppConfig, config
from clip_planner import ClipPlan, ClipPlanItem
from job import JobWorkspace
from pipeline import RunContext, VideoPipeline, build_final_composite_command


class RecordingPipeline(VideoPipeline):
    def __init__(self, fail_step=None):
        self.fail_step = fail_step
        self.calls = []

    def _run_named_step(self, name, ctx):
        self.calls.append(name)
        if name == self.fail_step:
            raise RuntimeError("planned failure")


class PipelineLifecycleTests(unittest.TestCase):
    def test_final_composite_command_has_explicit_narration_duration_limit(self):
        command = build_final_composite_command(
            ["ffmpeg", "-y", "-i", "timeline.mp4", "-i", "voice.mp3"],
            "[0:v]null[out_video]",
            ["-c:v", "libx264"],
            "final.mp4",
            narration_duration=16.992,
        )
        limit_index = command.index("-t")
        self.assertEqual(command[limit_index + 1], "16.992000")
        self.assertEqual(command[-1], "final.mp4")

    def test_pipeline_orders_content_timing_detection_planning_and_rendering(self):
        expected = (
            "content", "tts", "subtitle", "person_detection",
            "clip_plan", "timeline_render", "effects_prepare", "composite",
            "jianying_draft", "record",
        )
        self.assertEqual(tuple(name for name, _ in VideoPipeline.STEP_METHODS), expected)

    def test_draft_step_reuses_exact_clip_plan_audio_and_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = self.make_config(Path(tmp))
            config.bind(loaded)
            workspace = JobWorkspace.create(loaded, "草稿任务")
            audio = workspace.temp_dir / "tts_audio.mp3"
            srt = workspace.temp_dir / "auto_subtitle.srt"
            audio.write_bytes(b"audio")
            srt.write_text("subtitle", encoding="utf-8")
            plan = ClipPlan(2.0, 2.0, 4.0, (
                ClipPlanItem(str(Path(tmp) / "source.mp4"), 1.0, 5.0, 2.0, 2.0),
            ))
            ctx = RunContext("草稿任务", workspace)
            ctx.clip_plan = plan
            ctx.tts_audio_path = str(audio)
            ctx.srt_path = str(srt)
            ctx.dedup_clips = [str(Path(tmp) / "dedup.mp4")]
            ctx.use_stickers = [str(Path(tmp) / "sticker.png")]
            ctx.selected_filters = [("filter_01_暖色调.txt", "eq=warm")]

            fake_blueprint = object()
            fake_result = SimpleNamespace(
                draft_dir=workspace.output_dir / "jianying_draft" / "editable",
                manifest_path=workspace.output_dir / "jianying_draft" / "editable" / "draft_manifest.json",
            )
            with patch("pipeline.build_draft_blueprint", return_value=fake_blueprint) as build, \
                 patch("pipeline.generate_jianying_draft", return_value=fake_result) as generate, \
                 patch("pipeline.validate_draft_structure", return_value=SimpleNamespace(
                     passed=True, status="structure_passed_manual_open_pending", as_dict=lambda: {}
                 )):
                VideoPipeline()._step_jianying_draft(ctx)

            build.assert_called_once()
            args = build.call_args.args
            self.assertIs(args[1], plan)
            self.assertEqual(args[2:4], (str(audio), str(srt)))
            self.assertEqual(build.call_args.kwargs["dedup_paths"], ctx.dedup_clips)
            self.assertEqual(build.call_args.kwargs["dedup_alpha"], config.DEDUP_ALPHA)
            self.assertEqual(build.call_args.kwargs["sticker_paths"], ctx.use_stickers)
            self.assertEqual(build.call_args.kwargs["selected_filters"], ctx.selected_filters)
            self.assertEqual(build.call_args.kwargs["sticker_scale"], config.STICKER_SCALE)
            self.assertEqual(build.call_args.kwargs["sticker_alpha"], config.STICKER_ALPHA)
            self.assertEqual(
                build.call_args.kwargs["filter_intensity"],
                config.FILTER_BLEND_OPACITY * 100,
            )
            generate.assert_called_once_with(
                fake_blueprint, workspace.output_dir / "jianying_draft"
            )
            self.assertEqual(ctx.jianying_draft_dir, str(fake_result.draft_dir))

    def make_config(self, root: Path) -> AppConfig:
        path = root / "config.yaml"
        path.write_text(
            "\n".join(
                [
                    f'base_dir: "{str(root).replace(chr(92), chr(92) * 2)}"',
                    'output_subdir: "测试任务"',
                    'video_encoder: "libx264"',
                    'deepseek_api_key: ""',
                ]
            ),
            encoding="utf-8",
        )
        return AppConfig.from_file(str(path), environ={})

    def test_successful_pipeline_writes_completed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = self.make_config(Path(tmp))
            config.bind(loaded)
            pipeline = RecordingPipeline()

            ctx = pipeline.run("成功任务", overwrite=False, skip_preflight=True)

            payload = json.loads(ctx.workspace.status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "completed")
            self.assertGreater(len(payload["completed_steps"]), 0)

    def test_failed_pipeline_records_failed_step_and_preserves_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = self.make_config(Path(tmp))
            config.bind(loaded)
            pipeline = RecordingPipeline(fail_step="subtitle")

            with self.assertRaises(RuntimeError):
                pipeline.run("失败任务", overwrite=False, skip_preflight=True)

            status_path = Path(loaded.TEMP_DIR) / "jobs" / "失败任务" / "status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["failed_step"], "subtitle")
            self.assertTrue(status_path.parent.exists())


if __name__ == "__main__":
    unittest.main()
