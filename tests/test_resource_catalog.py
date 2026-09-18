import json
import tempfile
import unittest
from pathlib import Path

from resource_catalog import scan_resource_catalog, write_resource_catalog


class DummyConfig:
    def __init__(self, root: Path):
        self.BASE_DIR = str(root)
        self.STICKER_DIR = str(root / "sticker_lib")
        self.FONT_LIB_DIR = str(root / "font_lib")
        self.FILTER_LIB_DIR = str(root / "filter_lib")
        self.VOICE_LIB_DIR = str(root / "voice_lib")
        self.VOICE_LIB_FILE = str(root / "voice_lib" / "voices.txt")


class ResourceCatalogTests(unittest.TestCase):
    def test_scans_existing_libraries_in_deterministic_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("sticker_lib", "font_lib", "filter_lib", "voice_lib"):
                (root / name).mkdir()
            (root / "sticker_lib" / "b.png").write_bytes(b"png")
            (root / "sticker_lib" / "a.webp").write_bytes(b"webp")
            (root / "font_lib" / "Z.ttf").write_bytes(b"font")
            (root / "filter_lib" / "warm.txt").write_text("eq=saturation=1.1", encoding="utf-8")
            (root / "voice_lib" / "voices.txt").write_text(
                "# comment\nzh-CN-YunxiNeural|男声\nzh-CN-XiaoxiaoNeural|女声\n",
                encoding="utf-8",
            )

            catalog = scan_resource_catalog(DummyConfig(root))

            self.assertEqual([item.name for item in catalog.stickers], ["a.webp", "b.png"])
            self.assertEqual(catalog.fonts[0].kind, "font")
            self.assertTrue(catalog.filters[0].ffmpeg_compatible)
            self.assertEqual([item.resource_id for item in catalog.voices], [
                "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"
            ])
            self.assertEqual(catalog.flower_text, [])
            self.assertEqual(catalog.notes["flower_text"], "未配置本地花字资源")

    def test_writes_json_manifest_with_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("sticker_lib", "font_lib", "filter_lib", "voice_lib"):
                (root / name).mkdir()
            sticker = root / "sticker_lib" / "贴纸.png"
            sticker.write_bytes(b"png")
            catalog = scan_resource_catalog(DummyConfig(root))

            target = write_resource_catalog(catalog, root / "resource_manifest.json")
            payload = json.loads(target.read_text(encoding="utf-8"))

            self.assertTrue(Path(payload["stickers"][0]["path"]).is_absolute())
            self.assertEqual(payload["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
