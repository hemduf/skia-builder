import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_skia_defaults", REPO_ROOT / "build-skia.py")
build_skia = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_skia)


class DefaultSkiaBranchTests(unittest.TestCase):
    def test_cli_defaults_to_pinned_m153_branch(self):
        builder = build_skia.SkiaBuildScript()
        with mock.patch.object(sys, "argv", ["build-skia.py", "linux"]):
            builder.parse_arguments()

        self.assertEqual("chrome/m153", build_skia.DEFAULT_SKIA_BRANCH)
        self.assertEqual(build_skia.DEFAULT_SKIA_BRANCH, builder.branch)


if __name__ == "__main__":
    unittest.main()
