import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "apply_dawn_ios_visionos",
    REPO_ROOT / "patches" / "apply_dawn_ios_visionos.py",
)
dawn_patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dawn_patch)


class DawnPatchCompatibilityTests(unittest.TestCase):
    def test_replace_once_rejects_upstream_drift(self):
        path = Path("third_party/dawn/BUILD.gn")
        with self.assertRaisesRegex(RuntimeError, "expected exactly one patch anchor"):
            dawn_patch.replace_once(path, "no expected anchor here", "anchor", "replacement")

    def test_replace_once_replaces_single_anchor(self):
        path = Path("third_party/dawn/BUILD.gn")
        self.assertEqual(
            "before replacement after",
            dawn_patch.replace_once(path, "before anchor after", "anchor", "replacement"),
        )


if __name__ == "__main__":
    unittest.main()
