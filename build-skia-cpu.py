#!/usr/bin/env python3

"""Run build-skia.py with GPU defaults removed for a true CPU-only build.

build-skia.py currently appends RELEASE_GN_ARGS after CPU-specific arguments.
RELEASE_GN_ARGS enables OpenGL and Graphite, which overrides the CPU-only
settings. This launcher loads the existing build script, removes those shared
GPU defaults, and then runs the normal builder with ``-variant cpu``.

This keeps the CPU build on the same code path as every other platform while
ensuring that Graphite, OpenGL, Vulkan and Dawn remain disabled.
"""

import importlib.util
import sys
from pathlib import Path


def load_builder():
    script_path = Path(__file__).resolve().with_name("build-skia.py")
    spec = importlib.util.spec_from_file_location("skia_builder", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    builder = load_builder()

    # CPU_ONLY_GN_ARGS already explicitly disables Graphite, GL and Vulkan,
    # while PLATFORM_GN_ARGS_CPU disables platform GPU backends such as Dawn.
    # Remove the later shared defaults that would otherwise re-enable them.
    builder.RELEASE_GN_ARGS = builder.RELEASE_GN_ARGS.replace(
        "skia_use_gl = true\n", ""
    ).replace(
        "skia_enable_graphite = true\n", ""
    )

    args = sys.argv[1:]
    if "-variant" in args:
        variant_index = args.index("-variant")
        if variant_index + 1 >= len(args) or args[variant_index + 1] != "cpu":
            raise SystemExit("build-skia-cpu.py only supports -variant cpu")
    else:
        sys.argv.extend(["-variant", "cpu"])

    builder.SkiaBuildScript().run()


if __name__ == "__main__":
    main()
