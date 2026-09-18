import builtins
import importlib
import sys
import unittest
from unittest.mock import patch


class LazyDependencyImportTests(unittest.TestCase):
    def test_pipeline_modules_do_not_import_network_clients_at_module_import_time(self):
        names = (
            "pipeline", "tts", "deepseek_subtitle", "copywriter",
            "edge_tts", "requests",
        )
        previous = {name: sys.modules.get(name) for name in names}
        for name in names:
            sys.modules.pop(name, None)
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name in {"edge_tts", "requests"}:
                raise AssertionError(f"eager network client import: {name}")
            return real_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=guarded_import):
                importlib.import_module("pipeline")
        finally:
            for name in names:
                sys.modules.pop(name, None)
                if previous[name] is not None:
                    sys.modules[name] = previous[name]


if __name__ == "__main__":
    unittest.main()
