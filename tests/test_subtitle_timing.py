import tempfile
import unittest
from pathlib import Path

from subtitle import (
    generate_srt_from_boundaries,
    move_subtitle_down,
    optimize_srt_layout,
    set_subtitle_font_size,
)
from tts import SpeechBoundary


class SubtitleTimingTests(unittest.TestCase):
    def test_applies_cumulative_lower_position_and_one_size_larger_font(self):
        style = "force_style='FontSize=14,Alignment=2,MarginV=72'"
        adjusted = move_subtitle_down(style, 0.235)
        adjusted = set_subtitle_font_size(adjusted, 15)
        self.assertIn("MarginV=55", adjusted)
        self.assertIn("FontSize=15", adjusted)

    def test_moves_bottom_aligned_subtitle_down_by_reducing_margin_fifteen_percent(self):
        style = "subtitles='caption.srt':force_style='FontSize=14,Alignment=2,MarginV=72'"
        adjusted = move_subtitle_down(style, 0.15)
        self.assertIn("MarginV=61", adjusted)

    def test_overflow_caption_uses_segmenter_and_outputs_at_most_two_lines_per_cue(self):
        text = "在毕节七星关区王大哥正在等待雨棚师傅上门精准测量尺寸"
        calls = []

        def segmenter(value, max_chars):
            calls.append((value, max_chars))
            return ["在毕节七星关区王大哥正在等待", "雨棚师傅上门精准测量尺寸"]

        content = f"1\n00:00:00,000 --> 00:00:06,000\n{text}\n\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caption.srt"
            path.write_text(content, encoding="utf-8")
            ai_calls = optimize_srt_layout(path, max_chars_per_line=12, segmenter=segmenter)
            blocks = [block for block in path.read_text(encoding="utf-8").strip().split("\n\n") if block]
        self.assertEqual(ai_calls, 1)
        self.assertEqual(calls, [(text, 24)])
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertLessEqual(len(block.splitlines()[2:]), 2)

    def test_short_caption_does_not_call_ai_segmenter(self):
        def unexpected(*_):
            raise AssertionError("short caption should not call AI")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caption.srt"
            path.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\n上门精准测量\n\n",
                encoding="utf-8",
            )
            ai_calls = optimize_srt_layout(path, max_chars_per_line=12, segmenter=unexpected)
        self.assertEqual(ai_calls, 0)

    def test_uses_real_boundaries_and_never_exceeds_audio_duration(self):
        boundaries = [
            SpeechBoundary("在毕节七星关区，", 0.20, 1.80),
            SpeechBoundary("师傅上门测量。", 2.20, 4.60),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "caption.srt"
            source = generate_srt_from_boundaries(
                "在毕节七星关区，师傅上门测量。", boundaries, 5.0, path
            )
            content = path.read_text(encoding="utf-8")
        self.assertEqual(source, "word_boundary")
        self.assertIn("00:00:00,200 --> 00:00:01,800", content)
        self.assertIn("00:00:02,200 --> 00:00:04,600", content)
        self.assertNotIn("00:00:05,001", content)


if __name__ == "__main__":
    unittest.main()
