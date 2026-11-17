import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'validate_windows_arm64', ROOT / 'tools' / 'validate_windows_arm64.py')
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class Arm64PackageTests(unittest.TestCase):
    def test_all_coff_members_must_be_arm64(self):
        arm = 'Machine: IMAGE_FILE_MACHINE_ARM64 (0xAA64)\n'
        validator.validate_machine_headers(arm * 2)
        for output in ('', 'not a COFF archive',
                       arm + 'Machine: IMAGE_FILE_MACHINE_AMD64 (0x8664)\n',
                       'Machine: IMAGE_FILE_MACHINE_ARM64EC (0xA641)\n'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                validator.validate_machine_headers(output)

    def test_both_ganesh_gl_entry_points_are_required(self):
        symbols = 'GrGLMakeAssembledInterface()\nGrDirectContexts::MakeGL(sk_sp<GrGLInterface const>)'
        validator.validate_gl_symbols(symbols)
        for output in ('', 'GrGLMakeAssembledInterface()', 'GrDirectContexts::MakeGL()',
                       'GrGLMakeNativeInterface() GrDirectContexts::MakeGL()'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                validator.validate_gl_symbols(output)

    def test_missing_libraries_fail_before_invoking_llvm(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(validator.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'Missing required library'):
                validator.validate_package(Path(tmp))
            run.assert_not_called()

    def test_validation_runs_on_each_archive_and_checks_defined_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in validator.REQUIRED_LIBRARIES:
                (directory / name).touch()
            def inspect(command, **kwargs):
                if command[0] == 'llvm-readobj':
                    return mock.Mock(stdout='Machine: IMAGE_FILE_MACHINE_ARM64 (0xAA64)\n')
                self.assertIn('--defined-only', command)
                return mock.Mock(stdout='GrGLMakeAssembledInterface() GrDirectContexts::MakeGL()')
            with mock.patch.object(validator.subprocess, 'run', side_effect=inspect) as run:
                validator.validate_package(directory)
            self.assertEqual(len(validator.REQUIRED_LIBRARIES) + 1, run.call_count)


if __name__ == '__main__':
    unittest.main()
