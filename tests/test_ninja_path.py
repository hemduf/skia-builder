import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_skia", REPO_ROOT / "build-skia.py")
build_skia = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_skia)


class DepotToolsNinjaPathTests(unittest.TestCase):
    def test_native_ninja_precedes_depot_tools(self):
        builder = build_skia.SkiaBuildScript()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            depot_tools = root / "depot_tools"
            native_bin = root / "native-bin"
            depot_tools.mkdir()
            native_bin.mkdir()
            native_ninja = native_bin / ("ninja.exe" if os.name == "nt" else "ninja")

            original_depot_tools = build_skia.DEPOT_TOOLS_PATH
            build_skia.DEPOT_TOOLS_PATH = depot_tools
            try:
                initial_path = os.pathsep.join([str(depot_tools), str(native_bin)])
                with mock.patch.dict(os.environ, {"PATH": initial_path}, clear=False), \
                     mock.patch.object(build_skia.shutil, "which", return_value=str(native_ninja)) as which:
                    builder.setup_depot_tools()

                    searched_path = which.call_args.kwargs["path"].split(os.pathsep)
                    self.assertNotIn(str(depot_tools), searched_path)
                    self.assertIn(str(native_bin), searched_path)

                    final_path = os.environ["PATH"].split(os.pathsep)
                    self.assertEqual(str(native_bin), final_path[0])
                    self.assertEqual(str(depot_tools), final_path[1])
            finally:
                build_skia.DEPOT_TOOLS_PATH = original_depot_tools

    def test_missing_native_ninja_fails_early(self):
        builder = build_skia.SkiaBuildScript()

        with mock.patch.object(build_skia.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Native Ninja executable not found"):
                builder.setup_depot_tools()


if __name__ == "__main__":
    unittest.main()
