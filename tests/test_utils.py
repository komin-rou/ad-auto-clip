import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import (
    CommandExecutionError, MediaProbeError, check_tool, probe_media,
    probe_media_cached, run_command,
)


class UtilsTests(unittest.TestCase):
    def test_probe_media_cache_avoids_second_ffprobe_call(self):
        payload = {
            "streams": [{"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/1"}],
            "format": {"duration": "4.0"},
        }
        calls = 0

        def runner(*args, **kwargs):
            nonlocal calls
            calls += 1
            return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(payload), stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "clip.mp4"
            media.write_bytes(b"fixture")
            cache = Path(tmp) / "probe-cache"
            first = probe_media_cached(str(media), str(cache), runner=runner)
            second = probe_media_cached(str(media), str(cache), runner=runner)
        self.assertEqual(calls, 1)
        self.assertEqual(first, second)
    def test_check_tool_returns_false_for_nonzero_exit(self):
        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="broken")

        result = check_tool("ffmpeg", runner=runner)

        self.assertFalse(result.available)
        self.assertIn("broken", result.detail)

    def test_run_command_error_contains_context_exit_code_and_stderr_tail(self):
        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 9, stdout="", stderr="codec unavailable")

        with self.assertRaises(CommandExecutionError) as caught:
            run_command(["ffmpeg", "-version"], context="编码预检", runner=runner)

        message = str(caught.exception)
        self.assertIn("编码预检", message)
        self.assertIn("退出码 9", message)
        self.assertIn("codec unavailable", message)

    def test_probe_media_rejects_missing_video_stream(self):
        payload = {
            "streams": [{"codec_type": "audio"}],
            "format": {"duration": "3.5"},
        }

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(payload), stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "audio-only.mp4"
            media.write_bytes(b"fixture")
            with self.assertRaises(MediaProbeError):
                probe_media(str(media), runner=runner, require_video=True)

    def test_probe_media_returns_typed_duration_and_dimensions(self):
        payload = {
            "streams": [
                {"codec_type": "video", "width": 720, "height": 1280, "r_frame_rate": "30/1"},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "12.25"},
        }

        def runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(payload), stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "clip.mp4"
            media.write_bytes(b"fixture")
            info = probe_media(str(media), runner=runner)

        self.assertEqual(info.duration, 12.25)
        self.assertEqual((info.width, info.height), (720, 1280))
        self.assertTrue(info.has_audio)


if __name__ == "__main__":
    unittest.main()
