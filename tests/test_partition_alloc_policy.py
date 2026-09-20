import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_skia_partition_alloc", REPO_ROOT / "build-skia.py"
)
build_skia = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_skia)


class PartitionAllocPolicyTests(unittest.TestCase):
    def test_static_gpu_packages_disable_partition_alloc_without_disabling_dawn(self):
        builder = build_skia.SkiaBuildScript()
        builder.platform = "linux"
        builder.variant = "gpu"
        builder.config = "Release"
        builder.crt = "MT"

        summary = builder.generate_gn_args_summary("x64")

        self.assertIn("skia_use_partition_alloc = false", summary)
        self.assertIn("skia_use_dawn = true", summary)


if __name__ == "__main__":
    unittest.main()
