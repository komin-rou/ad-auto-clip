import tempfile
import unittest
from pathlib import Path

from config import AppConfig, config
from effects import build_sticker_chain, build_sticker_positions
from libraries import pick_random_stickers


class StickerEffectTests(unittest.TestCase):
    def test_position_count_matches_requested_sticker_count(self):
        for count in (0, 1, 2, 4, 6):
            with self.subTest(count=count):
                self.assertEqual(len(build_sticker_positions(count)), count)

    def test_zero_stickers_leave_stream_and_input_index_unchanged(self):
        inputs, filters, stream, next_index = build_sticker_chain(
            [], [], start_input_idx=7, base_stream="[base]"
        )

        self.assertEqual(inputs, [])
        self.assertEqual(filters, [])
        self.assertEqual(stream, "[base]")
        self.assertEqual(next_index, 7)

    def test_two_stickers_create_two_inputs_and_two_overlays(self):
        positions = build_sticker_positions(2)
        inputs, filters, stream, next_index = build_sticker_chain(
            ["one.png", "two.png"], positions, start_input_idx=3, base_stream="[base]"
        )

        self.assertEqual(inputs, ["-loop", "1", "-i", "one.png", "-loop", "1", "-i", "two.png"])
        self.assertEqual(sum("overlay=" in part for part in filters), 2)
        self.assertEqual(stream, "[tmp4]")
        self.assertEqual(next_index, 5)

    def test_mismatched_positions_are_rejected(self):
        with self.assertRaises(ValueError):
            build_sticker_chain(["one.png"], [], 2, "[base]")

    def test_insufficient_sticker_library_raises_regular_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sticker_lib").mkdir()
            (root / "sticker_lib" / "only.png").write_bytes(b"png")
            config_path = root / "config.yaml"
            config_path.write_text(
                f'base_dir: "{str(root).replace(chr(92), chr(92) * 2)}"\n'
                'video_encoder: "libx264"\n'
                'sticker_count: 2\n',
                encoding="utf-8",
            )
            config.bind(AppConfig.from_file(str(config_path), environ={}))

            with self.assertRaises(ValueError):
                pick_random_stickers()


if __name__ == "__main__":
    unittest.main()
