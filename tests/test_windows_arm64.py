import contextlib
import importlib.util
import io
import re
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_skia_arm64', ROOT / 'build-skia.py')
builder_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder_module)


class WindowsArm64Tests(unittest.TestCase):
    def test_actual_gn_arguments_preserve_gl_and_crt_for_arm64(self):
        for arch in ('arm64', 'x64'):
            for config in ('Debug', 'Release'):
                for crt in ('MT', 'MD'):
                    with self.subTest(arch=arch, config=config, crt=crt):
                        builder = builder_module.SkiaBuildScript()
                        builder.platform, builder.config, builder.crt = 'win', config, crt
                        with mock.patch.object(builder_module.subprocess, 'run') as run, \
                             mock.patch.object(builder_module.os.path, 'isdir', return_value=False), \
                             contextlib.redirect_stdout(io.StringIO()):
                            builder.generate_gn_args(arch)
                        args = run.call_args.args[0][-1]
                        values = dict(re.findall(r'(\w+)\s*=\s*([^\n]+)', args))
                        self.assertEqual('true', values['skia_use_gl'])
                        self.assertEqual(f'"{arch}"', values['target_cpu'])
                        suffix = 'd' if config == 'Debug' else ''
                        self.assertEqual(f'["/{crt}{suffix}"]', values['extra_cflags'])
                        self.assertEqual('true', values['skia_use_dawn'])
                        self.assertEqual(arch == 'x64', builder.win_angle_enabled(arch))


if __name__ == '__main__':
    unittest.main()
