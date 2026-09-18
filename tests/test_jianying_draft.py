import json
import os
import tempfile
import unittest
from pathlib import Path

from clip_planner import ClipPlan, ClipPlanItem
from jianying_draft import (
    build_draft_blueprint,
    generate_jianying_draft,
    validate_draft_structure,
)
from style_presets import DEFAULT_PORTRAIT_PRESET


class FakeTrackType:
    audio = "audio"
    video = "video"
    text = "text"
    filter = "filter"


class FakeTrackSpec:
    def __init__(self, track_type, name):
        self.track_type = track_type
        self.name = name


class FakeTrackRef:
    def __init__(self, name):
        self.name = name


class FakeClipSettings:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeTextStyle:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeTextBorder:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeSegment:
    def __init__(self, material, target_timerange=None, **kwargs):
        self.material = material
        self.target_timerange = target_timerange
        self.kwargs = kwargs
        self.filters = []
        self.mix_modes = []

    def add_filter(self, filter_type, intensity=100.0):
        self.filters.append((filter_type, intensity))
        return self

    def set_mix_mode(self, mix_mode):
        self.mix_modes.append(mix_mode)
        return self


class FakeFilterType:
    日落橘 = "warm"
    冷蓝 = "cool"


class FakeMixModeType:
    叠加 = "overlay"


class FakeScript:
    def __init__(self, draft_dir: Path):
        self.draft_dir = draft_dir
        self.tracks = []
        self.segments = []
        self.srt = None
        self.saved = False
        self.filters = []
        self.localappdata_during_save = "not-called"

    def append_tracks(self, specs):
        self.tracks.extend(specs)
        return tuple(FakeTrackRef(spec.name) for spec in specs)

    def add_segment(self, segment, track):
        self.segments.append((track, segment))

    def import_srt(self, path, track_name, **kwargs):
        self.srt = (path, track_name, kwargs)

    def add_filter(self, filter_meta, timerange, track_name=None, intensity=100.0):
        self.filters.append((filter_meta, timerange, track_name, intensity))

    def save(self):
        self.saved = True
        self.localappdata_during_save = os.environ.get("LOCALAPPDATA")
        self.draft_dir.mkdir(parents=True, exist_ok=True)
        tracks = [
            {"type": "audio", "name": "narration", "segments": [{}]},
            {"type": "video", "name": "main_video", "segments": [{}, {}]},
            {"type": "text", "name": "captions", "segments": [{}]},
        ]
        tracks.extend(
            {"type": spec.track_type, "name": spec.name, "segments": [{}]}
            for spec in self.tracks
            if spec.name.startswith(("dedup_", "sticker_", "filter_"))
        )
        materials = {
            "videos": [{"path": segment.material} for track, segment in self.segments
                       if track.name == "main_video"],
            "audios": [{"path": segment.material} for track, segment in self.segments
                       if track.name == "narration"],
        }
        content = {
            "canvas_config": {"width": 1080, "height": 1920},
            "fps": 30,
            "duration": 5_000_000,
            "tracks": tracks,
            "materials": materials,
        }
        (self.draft_dir / "draft_content.json").write_text(
            json.dumps(content), encoding="utf-8"
        )
        (self.draft_dir / "draft_meta_info.json").write_text(
            json.dumps({"draft_id": "fake-draft-id", "draft_name": ""}),
            encoding="utf-8",
        )


class FakeDraftFolder:
    last_instance = None

    def __init__(self, root):
        self.root = Path(root)
        self.created = None
        FakeDraftFolder.last_instance = self

    def create_draft(self, name, width, height, fps=30, allow_replace=False):
        self.created = (name, width, height, fps, allow_replace)
        self.script = FakeScript(self.root / name)
        return self.script


class FakeDraftModule:
    DraftFolder = FakeDraftFolder
    TrackType = FakeTrackType
    TrackSpec = FakeTrackSpec
    ClipSettings = FakeClipSettings
    TextStyle = FakeTextStyle
    TextBorder = FakeTextBorder
    TextSegment = FakeSegment
    VideoSegment = FakeSegment
    AudioSegment = FakeSegment
    FilterType = FakeFilterType
    MixModeType = FakeMixModeType

    @staticmethod
    def trange(start, duration):
        return (start, duration)


class JianyingDraftTests(unittest.TestCase):
    def _plan(self):
        return ClipPlan(
            speed=2.0,
            narration_duration=5.0,
            available_source_duration=20.0,
            items=(
                ClipPlanItem("D:/clips/a.mp4", 1.0, 7.0, 2.0, 3.0),
                ClipPlanItem("D:/clips/b.mp4", 2.0, 6.0, 2.0, 2.0),
            ),
        )

    def test_blueprint_uses_portrait_canvas_and_exact_clip_plan(self):
        blueprint = build_draft_blueprint(
            "昆明市五华区", self._plan(), "D:/job/tts.mp3", "D:/job/caption.srt",
            DEFAULT_PORTRAIT_PRESET,
        )

        self.assertEqual((blueprint.width, blueprint.height, blueprint.fps), (1080, 1920, 30))
        self.assertEqual([item.target_start for item in blueprint.video_items], [0.0, 3.0])
        self.assertEqual([item.source_start for item in blueprint.video_items], [1.0, 2.0])
        self.assertEqual([item.speed for item in blueprint.video_items], [2.0, 2.0])
        self.assertTrue(all(item.volume == 0.0 for item in blueprint.video_items))
        self.assertEqual(blueprint.narration.target_start, 0.0)
        self.assertEqual(blueprint.narration.duration, 5.0)
        self.assertEqual(blueprint.subtitle_style.max_lines, 2)
        self.assertEqual(blueprint.subtitle_style.color, (1.0, 1.0, 1.0))

    def test_adapter_creates_editable_video_audio_and_srt_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "tts.mp3"
            srt = root / "caption.srt"
            audio.write_bytes(b"audio")
            srt.write_text("1\n00:00:00,000 --> 00:00:05,000\n字幕\n", encoding="utf-8")
            plan = self._plan()
            plan = ClipPlan(plan.speed, plan.narration_duration, plan.available_source_duration, tuple(
                ClipPlanItem(str(root / Path(item.source).name), item.source_start, item.source_end,
                             item.speed, item.output_duration)
                for item in plan.items
            ))
            for item in plan.items:
                Path(item.source).write_bytes(b"video")
            blueprint = build_draft_blueprint(
                "测试地点", plan, str(audio), str(srt), DEFAULT_PORTRAIT_PRESET,
                dedup_paths=[str(root / "dedup-0.mp4"), str(root / "dedup-1.mp4")],
                dedup_alpha=0.03,
                sticker_paths=[str(root / "top-left.png"), str(root / "bottom-right.png")],
                selected_filters=[("filter_01_暖色调.txt", "eq=warm")],
                sticker_scale=0.05,
                sticker_alpha=0.08,
                filter_intensity=2.0,
            )
            (root / "top-left.png").write_bytes(b"png")
            (root / "bottom-right.png").write_bytes(b"png")
            (root / "dedup-0.mp4").write_bytes(b"video")
            (root / "dedup-1.mp4").write_bytes(b"video")

            previous_localappdata = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = str(root / "must-not-touch")
            try:
                result = generate_jianying_draft(
                    blueprint, root / "jianying_draft", draft_module=FakeDraftModule
                )
                self.assertEqual(os.environ.get("LOCALAPPDATA"), str(root / "must-not-touch"))
            finally:
                if previous_localappdata is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous_localappdata

            folder = FakeDraftFolder.last_instance
            self.assertEqual(folder.created, ("editable", 1080, 1920, 30, True))
            self.assertEqual([spec.name for spec in folder.script.tracks], [
                "narration", "main_video", "dedup_0", "dedup_1", "captions",
                "sticker_0", "sticker_1", "filter_0",
            ])
            self.assertEqual(len(folder.script.segments), 7)
            dedup_segments = [
                segment for track, segment in folder.script.segments
                if track.name.startswith("dedup_")
            ]
            self.assertEqual(
                [segment.kwargs["clip_settings"].kwargs["alpha"] for segment in dedup_segments],
                [0.03, 0.03],
            )
            self.assertEqual(
                [segment.mix_modes for segment in dedup_segments],
                [["overlay"], ["overlay"]],
            )
            sticker_segments = [
                segment for track, segment in folder.script.segments
                if track.name.startswith("sticker_")
            ]
            self.assertEqual(
                [segment.kwargs["clip_settings"].kwargs["alpha"] for segment in sticker_segments],
                [0.08, 0.08],
            )
            self.assertEqual(
                [segment.kwargs["clip_settings"].kwargs["scale_x"] for segment in sticker_segments],
                [0.05, 0.05],
            )
            self.assertEqual(folder.script.filters, [
                ("warm", ("0.000000s", "5.000000s"), "filter_0", 2.0)
            ])
            self.assertEqual(folder.script.srt[1], "captions")
            self.assertIn("style_reference", folder.script.srt[2])
            self.assertIsNone(folder.script.srt[2]["clip_settings"])
            self.assertTrue(folder.script.saved)
            self.assertIsNone(folder.script.localappdata_during_save)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["canvas"], {"width": 1080, "height": 1920, "fps": 30})
            self.assertEqual(manifest["track_counts"], {
                "video": 2, "audio": 1, "text": 1, "dedup": 2,
                "sticker": 2, "filter": 1,
            })
            self.assertEqual(len(manifest["dedup_layers"]), 2)
            self.assertEqual(len(manifest["stickers"]), 2)
            self.assertEqual(manifest["filters"], [{
                "source_name": "filter_01_暖色调.txt",
                "jianying_filter": "日落橘",
                "intensity": 2.0,
            }])

            report = validate_draft_structure(result.draft_dir)
            self.assertTrue(report.passed)
            self.assertEqual(report.status, "structure_passed_manual_open_pending")

            verified = validate_draft_structure(
                result.draft_dir,
                manual_open_confirmed=True,
                jianying_version="10.7.0",
            )
            self.assertTrue(verified.passed)
            self.assertEqual(verified.status, "verified_jianying_10_7_0")
            self.assertTrue(verified.manual_open_confirmed)
            self.assertEqual(verified.jianying_version, "10.7.0")

            native = json.loads((result.draft_dir / "draft_content.json").read_text(encoding="utf-8"))
            native["tracks"] = [
                track for track in native["tracks"] if track.get("name") != "filter_0"
            ]
            (result.draft_dir / "draft_content.json").write_text(
                json.dumps(native), encoding="utf-8"
            )
            missing_filter = validate_draft_structure(result.draft_dir)
            self.assertFalse(missing_filter.passed)
            self.assertTrue(any("原生滤镜轨道数量不足" in issue for issue in missing_filter.issues))

            folder.script.save()

            manifest["track_counts"]["video"] = "bogus"
            manifest["video_items"] = "not-a-list"
            manifest["narration"] = []
            result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            malformed = validate_draft_structure(result.draft_dir)
            self.assertFalse(malformed.passed)
            self.assertEqual(malformed.status, "structure_failed")
            self.assertTrue(any("轨道数量格式错误" in issue for issue in malformed.issues))
            self.assertTrue(any("视频素材清单格式错误" in issue for issue in malformed.issues))
            self.assertTrue(any("旁白清单格式错误" in issue for issue in malformed.issues))

            manifest["track_counts"] = {"video": 2, "audio": 1, "text": 1}
            manifest["video_items"] = [{"source": []}]
            manifest["narration"] = {"source": 123, "duration": 5.0}
            manifest["srt_path"] = {"invalid": "path"}
            result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            malformed_paths = validate_draft_structure(result.draft_dir)
            self.assertFalse(malformed_paths.passed)
            self.assertGreaterEqual(
                sum("素材路径格式错误" in issue for issue in malformed_paths.issues), 3
            )

    def test_validation_reports_missing_material_without_claiming_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft_dir = Path(tmp)
            (draft_dir / "draft_content.json").write_text("{}", encoding="utf-8")
            (draft_dir / "draft_meta_info.json").write_text("{}", encoding="utf-8")
            (draft_dir / "draft_manifest.json").write_text(json.dumps({
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "duration": 5.0,
                "track_counts": {"video": 1, "audio": 1, "text": 1},
                "video_items": [{"source": str(draft_dir / "missing.mp4")}],
                "narration": {"source": str(draft_dir / "missing.mp3")},
                "srt_path": str(draft_dir / "missing.srt"),
            }), encoding="utf-8")

            report = validate_draft_structure(draft_dir)

            self.assertFalse(report.passed)
            self.assertEqual(report.status, "structure_failed")
            self.assertTrue(any("素材不存在" in issue for issue in report.issues))

    def test_validation_rejects_native_draft_without_canvas_tracks_and_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft_dir = Path(tmp)
            material = draft_dir / "video.mp4"
            audio = draft_dir / "voice.mp3"
            srt = draft_dir / "caption.srt"
            for path in (material, audio, srt):
                path.write_bytes(b"data")
            (draft_dir / "draft_content.json").write_text("{}", encoding="utf-8")
            (draft_dir / "draft_meta_info.json").write_text("{}", encoding="utf-8")
            (draft_dir / "draft_manifest.json").write_text(json.dumps({
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "duration": 5.0,
                "track_counts": {"video": 1, "audio": 1, "text": 1},
                "video_items": [{"source": str(material)}],
                "narration": {"source": str(audio), "duration": 5.0},
                "srt_path": str(srt),
            }), encoding="utf-8")

            report = validate_draft_structure(draft_dir)

            self.assertFalse(report.passed)
            self.assertTrue(any("原生草稿画布" in issue for issue in report.issues))
            self.assertTrue(any("原生草稿轨道" in issue for issue in report.issues))
            self.assertTrue(any("原生草稿时长" in issue for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
