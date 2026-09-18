import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


class SubtitleSlicerPortabilityTests(unittest.TestCase):
    def test_base_directory_follows_script_location(self):
        source = Path(__file__).resolve().parents[1] / "tools" / "subtitle_slicer.py"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "portable-project"
            tools = project / "tools"
            tools.mkdir(parents=True)
            copied = tools / "subtitle_slicer.py"
            shutil.copy2(source, copied)

            spec = importlib.util.spec_from_file_location("portable_subtitle_slicer", copied)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)

            self.assertEqual(Path(module.BASE_DIR), project.resolve())
            self.assertEqual(Path(module.SUBTITLE_DIR), project.resolve() / "subtitles")


if __name__ == "__main__":
    unittest.main()
