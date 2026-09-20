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
    def assert_static_gpu_policy(self, platform, arch, crt="MT"):
        builder = build_skia.SkiaBuildScript()
        builder.platform = platform
        builder.variant = "gpu"
        builder.config = "Release"
        builder.crt = crt

        summary = builder.generate_gn_args_summary(arch)

        self.assertIn("skia_use_partition_alloc = false", summary)
        self.assertIn("skia_use_dawn = true", summary)

    def test_linux_static_gpu_disables_partition_alloc_without_disabling_dawn(self):
        self.assert_static_gpu_policy("linux", "x64")

    def test_windows_md_static_gpu_disables_partition_alloc_without_disabling_dawn(self):
        self.assert_static_gpu_policy("win", "x64", crt="MD")


if __name__ == "__main__":
    unittest.main()
