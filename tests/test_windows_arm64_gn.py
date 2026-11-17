import contextlib
import importlib.util
import io
import os
import platform
import runpy
import sys
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_skia_gn', ROOT / 'build-skia.py')
builder_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder_module)
FIXTURE = (ROOT / 'tests/fixtures/fetch_gn_m153.py').read_text()
REVISION = 'b2afae122eeb6ce09c52d63f67dc53fc517dbdc8'


class WindowsArm64GnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'bin').mkdir()
        self.fetch = self.root / 'bin/fetch-gn'
        self.fetch.write_text(FIXTURE)
        self.archive = io.BytesIO()
        with zipfile.ZipFile(self.archive, 'w') as archive:
            archive.writestr('gn.exe', b'fixture GN Windows executable')
            archive.writestr('gn', b'fixture GN Unix executable')

    def prepare(self, host='arm64', os_name='win32'):
        with mock.patch.object(builder_module, 'SKIA_SRC_DIR', self.root), \
             mock.patch.object(sys, 'platform', os_name), \
             mock.patch.object(platform, 'machine', return_value=host), \
             contextlib.redirect_stdout(io.StringIO()):
            builder_module.SkiaBuildScript().setup_gn_for_windows_arm64()

    def execute_downloader(self, host, os_name, error=None):
        # Execute the upstream downloader, not a reimplementation of URL selection.
        download_dir = self.root / 'download'
        download_dir.mkdir(exist_ok=True)
        cwd = os.getcwd()
        try:
            with mock.patch.object(sys, 'platform', os_name), \
                 mock.patch.object(platform, 'machine', return_value=host), \
                 mock.patch.object(tempfile, 'mkdtemp', return_value=str(download_dir)), \
                 mock.patch.object(urllib.request, 'urlopen',
                     side_effect=error or (lambda url: io.BytesIO(self.archive.getvalue()))) as urlopen:
                runpy.run_path(str(self.fetch))
                return urlopen.call_args.args[0]
        finally:
            os.chdir(cwd)

    def test_windows_arm64_uses_pinned_x64_package_and_upstream_locations(self):
        for host in ('arm64', 'aarch64'):
            with self.subTest(host=host):
                # Prevent accidental real I/O from the old, broken setup method.
                with mock.patch.object(urllib.request, 'urlopen',
                                       side_effect=lambda url: io.BytesIO(self.archive.getvalue())):
                    self.prepare(host)
                url = self.execute_downloader(host, 'win32')
                self.assertEqual(
                    f'https://chrome-infra-packages.appspot.com/dl/gn/gn/windows-amd64/+/git_revision:{REVISION}', url)
                self.assertEqual(b'fixture GN Windows executable', (self.root / 'bin/gn.exe').read_bytes())
                self.assertEqual((self.root / 'bin/gn.exe').read_bytes(),
                                 (self.root / 'third_party/gn/gn.exe').read_bytes())

    def test_patch_is_idempotent_even_with_existing_gn(self):
        with mock.patch.object(urllib.request, 'urlopen',
                               side_effect=lambda url: io.BytesIO(self.archive.getvalue())):
            self.prepare()
            first = self.fetch.read_text()
            (self.root / 'bin/gn.exe').write_bytes(b'existing')
            self.prepare()
        self.assertEqual(first, self.fetch.read_text())
        self.assertNotIn('/+/latest', self.fetch.read_text())

    def test_other_hosts_keep_upstream_package_selection(self):
        self.prepare()
        for host, os_name, package in (
                ('AMD64', 'win32', 'windows-amd64'),
                ('arm64', 'darwin', 'mac-arm64'),
                ('aarch64', 'linux', 'linux-arm64')):
            with self.subTest(host=host, os_name=os_name):
                self.prepare(host, os_name)
                url = self.execute_downloader(host, os_name)
                self.assertTrue(url.endswith(f'{package}/+/git_revision:{REVISION}'), url)

    def test_source_drift_is_fatal(self):
        anchor = "  cpu = {'aarch64': 'arm64', 'amd64': 'amd64', 'arm64': 'arm64', 'x86_64': 'amd64'}[platform.machine().lower()]"
        for source in ('unexpected upstream source\n', FIXTURE.replace(anchor, anchor + '\n' + anchor)):
            with self.subTest(source=source[:20]):
                self.fetch.write_text(source)
                with self.assertRaisesRegex(RuntimeError, 'exactly one GN CPU mapping'):
                    self.prepare()

    def test_missing_source_is_fatal(self):
        self.fetch.unlink()
        with self.assertRaisesRegex(RuntimeError, 'fetch-gn'):
            self.prepare()

    def test_upstream_download_error_stays_fatal(self):
        with mock.patch.object(urllib.request, 'urlopen',
                               side_effect=lambda url: io.BytesIO(self.archive.getvalue())):
            self.prepare()
        with self.assertRaisesRegex(OSError, 'download failed'):
            self.execute_downloader('arm64', 'win32', OSError('download failed'))

    def test_preparation_runs_before_dependency_sync(self):
        builder = builder_module.SkiaBuildScript()
        builder.platform, builder.variant = 'win', 'cpu'
        events = []
        with contextlib.ExitStack() as stack:
            for name in ('parse_arguments', 'setup_depot_tools', 'setup_skia_repo',
                         'apply_patches', 'patch_dawn_crt_runtime', 'patch_angle_build_gn',
                         'package_headers', 'package_icu_data', 'write_gn_args_summary'):
                stack.enter_context(mock.patch.object(builder, name))
            stack.enter_context(mock.patch.object(builder, 'setup_gn_for_windows_arm64',
                                                  side_effect=lambda: events.append('prepare')))
            stack.enter_context(mock.patch.object(builder, 'sync_deps',
                                                  side_effect=lambda: events.append('sync')))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            builder.run()
        self.assertEqual(['prepare', 'sync'], events)


if __name__ == '__main__':
    unittest.main()
