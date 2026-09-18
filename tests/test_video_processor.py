import unittest

from clip_planner import ClipPlan, ClipPlanItem
from video_processor import build_aspect_filter, build_timeline_command


class TimelineCommandTests(unittest.TestCase):
    def test_shared_aspect_filter_never_uses_distorting_plain_scale(self):
        value = build_aspect_filter(1080, 1920, 30)
        self.assertEqual(
            value,
            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30",
        )

    def test_builds_aspect_safe_muted_concat_in_one_ffmpeg_command(self):
        plan = ClipPlan(
            speed=1.5,
            narration_duration=4.0,
            available_source_duration=10.0,
            items=(
                ClipPlanItem("a.mp4", 1.0, 4.0, 1.5, 2.0),
                ClipPlanItem("b.mp4", 2.0, 5.0, 1.5, 2.0),
            ),
        )
        command = build_timeline_command(plan, "timeline.mp4", 1080, 1920, 30, ["-c:v", "libx264"])
        joined = " ".join(command)
        self.assertEqual(command.count("-i"), 2)
        self.assertIn("force_original_aspect_ratio=increase", joined)
        self.assertIn("crop=1080:1920", joined)
        self.assertIn("setsar=1", joined)
        self.assertIn("setpts=(PTS-STARTPTS)/1.5", joined)
        self.assertIn("concat=n=2:v=1:a=0", joined)
        self.assertIn("-an", command)


if __name__ == "__main__":
    unittest.main()
