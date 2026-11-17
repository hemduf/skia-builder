import hashlib
import importlib.util
import io
import json
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('publish_arm64', ROOT / 'tools/publish_windows_arm64.py')
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries:
            archive.writestr(name, value)
    return output.getvalue()


def coff(machine=0xAA64):
    payload = struct.pack('<HHI', machine, 0, 0) + b'object'
    header = b'object.obj/     ' + b'0           ' + b'0     ' + b'0     ' + b'644     '
    header += str(len(payload)).encode().ljust(10) + b'`\n'
    return b'!<arch>\n' + header + payload + (b'\n' if len(payload) & 1 else b'')


def source():
    run = {'id': publisher.SOURCE_RUN, 'head_sha': publisher.SOURCE_SHA,
           'repository': {'full_name': publisher.REPOSITORY},
           'head_repository': {'full_name': publisher.REPOSITORY},
           'status': 'completed', 'conclusion': 'failure', 'event': 'workflow_dispatch',
           'path': '.github/workflows/build-skia.yml', 'run_attempt': 1}
    jobs = []
    for crt, config, _, _ in publisher.MANIFEST.values():
        jobs.append({'name': f'build-skia (windows-11-arm, win, gpu, arm64, {config}, {crt})',
                     'status': 'completed', 'conclusion': 'success',
                     'steps': [{'name': n, 'conclusion': 'success'} for n in
                               (f'Build Skia ({config})', 'Validate Windows ARM64 package',
                                'Package binaries', 'Upload artifact')]})
    comparison = {'status': 'ahead', 'merge_base_commit': {'sha': publisher.SOURCE_SHA}}
    return run, jobs, comparison


class SourceTests(unittest.TestCase):
    def test_source_is_pinned_merged_and_each_required_job_really_validated(self):
        run, jobs, comparison = source()
        publisher.validate_source(run, jobs, comparison, publisher.SOURCE_RUN)
        for bad in (dict(run, id=1), dict(run, head_sha='f' * 40),
                    dict(run, event='pull_request'), dict(run, status='in_progress'),
                    dict(run, run_attempt=2), dict(run, head_repository={'full_name': 'fork/repo'})):
            with self.subTest(run=bad), self.assertRaises(ValueError):
                publisher.validate_source(bad, jobs, comparison, publisher.SOURCE_RUN)
        for bad in ({'status': 'diverged', 'merge_base_commit': {'sha': publisher.SOURCE_SHA}},
                    {'status': 'ahead', 'merge_base_commit': {'sha': 'f' * 40}}):
            with self.assertRaises(ValueError):
                publisher.validate_source(run, jobs, bad, publisher.SOURCE_RUN)
        for mutate in ('missing', 'failed', 'skipped', 'duplicate'):
            bad_jobs = json.loads(json.dumps(jobs))
            if mutate == 'missing':
                bad_jobs.pop()
            elif mutate == 'failed':
                bad_jobs[0]['conclusion'] = 'failure'
            elif mutate == 'skipped':
                bad_jobs[0]['steps'][1]['conclusion'] = 'skipped'
            else:
                bad_jobs.append(bad_jobs[0])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                publisher.validate_source(run, bad_jobs, comparison, publisher.SOURCE_RUN)

    def test_publication_ref_gate_precedes_all_network_calls(self):
        with mock.patch.dict(publisher.os.environ, {'GITHUB_REPOSITORY': publisher.REPOSITORY,
                                                  'GITHUB_REF': 'refs/heads/feature'}), \
             mock.patch.object(publisher, 'GitHub') as api, self.assertRaises(ValueError):
            publisher.publish(publisher.SOURCE_RUN, Path('unused'), True)
        api.assert_not_called()

    def test_artifact_provenance_and_duplicates(self):
        artifacts = [{'name': name, 'id': i + 1, 'expired': False, 'size_in_bytes': 30,
                      'digest': 'sha256:' + 'a' * 64,
                      'workflow_run': {'id': publisher.SOURCE_RUN, 'head_sha': publisher.SOURCE_SHA}}
                     for i, name in enumerate(publisher.MANIFEST)]
        self.assertEqual(set(publisher.MANIFEST), set(publisher.select_artifacts(artifacts)))
        for key, value in [('expired', True), ('digest', ''), ('workflow_run', {'id': 1}),
                           ('size_in_bytes', 0), ('name', 'skia-build-win-x64-gpu-release')]:
            bad = json.loads(json.dumps(artifacts))
            bad[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                publisher.select_artifacts(bad)
        with self.assertRaises(ValueError):
            publisher.select_artifacts(artifacts + [artifacts[0]])


class ZipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def test_unsafe_duplicate_or_symlink_members_are_rejected(self):
        for name in ('../escape', '/absolute', 'a/../escape', 'a\\escape', 'C:/escape',
                     'a//escape', './escape', 'a/./escape'):
            with self.subTest(name=name), zipfile.ZipFile(io.BytesIO(zip_bytes([(name, b'x')]))) as z:
                with self.assertRaises(ValueError):
                    publisher.safe_members(z)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            data = zip_bytes([('same', b'first'), ('same', b'second')])
        with zipfile.ZipFile(io.BytesIO(data)) as z, self.assertRaises(ValueError):
            publisher.safe_members(z)
        link = zipfile.ZipInfo('link')
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        with zipfile.ZipFile(io.BytesIO(zip_bytes([(link, b'/target')])) ) as z, \
             self.assertRaises(ValueError):
            publisher.safe_members(z)

    def test_wrapper_requires_exact_name_single_member_and_api_digest(self):
        name = next(iter(publisher.MANIFEST))
        for entries, valid in (([(name + '.zip', b'inner')], True),
                               ([('other.zip', b'inner')], False),
                               ([(name + '.zip', b'inner'), ('extra', b'x')], False)):
            wrapper = self.directory / 'wrapper.zip'
            wrapper.write_bytes(zip_bytes(entries))
            artifact = {'name': name, 'size_in_bytes': wrapper.stat().st_size,
                        'digest': 'sha256:' + publisher.sha256(wrapper)}
            if valid:
                output = publisher.unwrap_artifact(wrapper, artifact, self.directory)
                self.assertEqual(b'inner', output.read_bytes())
            else:
                with self.assertRaises(ValueError):
                    publisher.unwrap_artifact(wrapper, artifact, self.directory)
            artifact['digest'] = 'sha256:' + '0' * 64
            with self.assertRaises(ValueError):
                publisher.unwrap_artifact(wrapper, artifact, self.directory)

    def test_coff_rejects_mixed_archives_truncation_and_empty_libraries(self):
        publisher.validate_coff_archive(io.BytesIO(coff()))
        for data in (coff(0x8664), coff() + coff(0x8664)[8:], coff()[:-2],
                     b'!<arch>\n', b'not an archive'):
            with self.subTest(data=data[:20]), self.assertRaises(ValueError):
                publisher.validate_coff_archive(io.BytesIO(data))

    def package(self, name, metadata_change='', extra=(), missing=None):
        crt, config, _, _ = publisher.MANIFEST[name]
        variant = 'win-gpu-md' if crt == 'MD' else 'win-gpu'
        metadata = (f'Configuration: {config}\nVariant: gpu\nArchitectures: arm64\n'
                    f'target_cpu = "arm64"\ncrt = "{crt}"\nskia_use_gl = true\n')
        entries = [('build/include/include/core/SkCanvas.h', b'header'),
                   ('build/share/icudtl.dat', b'icu'),
                   (f'build/{variant}/lib/gn_args.txt', metadata.replace('arm64', metadata_change or 'arm64'))]
        entries += [(f'build/{variant}/lib/{config}/arm64/{lib}', coff()) for lib in publisher.LIBRARIES]
        entries = [entry for entry in entries if entry[0] != missing] + list(extra)
        path = self.directory / (name + '.zip')
        path.write_bytes(zip_bytes(entries))
        return path, (crt, config, path.stat().st_size, publisher.sha256(path))

    def test_inner_packages_validate_names_payload_cpu_metadata_and_measured_hash(self):
        name = 'skia-build-win-arm64-gpu-md-release'
        for change, extra, missing in (('', (), None), ('x64', (), None),
                                      ('', [('build/win-gpu-md/lib/Release/x64/skia.lib', coff())], None),
                                      ('', (), 'build/share/icudtl.dat')):
            package, pin = self.package(name, change, extra, missing)
            with mock.patch.dict(publisher.MANIFEST, {name: pin}):
                if change or extra or missing:
                    with self.assertRaises(ValueError):
                        publisher.validate_package(package, name)
                else:
                    self.assertEqual(pin[3], publisher.validate_package(package, name)['sha256'])
                    with package.open('ab') as stream:
                        stream.write(b'corruption')
                    with self.assertRaisesRegex(ValueError, 'reviewed binary manifest'):
                        publisher.validate_package(package, name)


class PlanTests(unittest.TestCase):
    def test_add_missing_only_reject_conflict_and_idempotent_skip(self):
        package = {'name': 'skia-build-win-arm64-gpu-release.zip', 'size': 100,
                   'sha256': 'a' * 64}
        asset = dict(package, digest='sha256:' + package['sha256'])
        self.assertEqual([package['name']], publisher.upload_plan([package], []))
        self.assertEqual([], publisher.upload_plan([package], [asset]))
        for bad in (dict(asset, size=99), dict(asset, digest='sha256:' + 'b' * 64),
                    dict(asset, digest=None)):
            with self.assertRaisesRegex(ValueError, 'Conflicting'):
                publisher.upload_plan([package], [bad])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            publisher.upload_plan([package], [asset, asset])


class PublicationTests(unittest.TestCase):
    def test_dry_run_is_read_only_then_publish_and_rerun_are_additive(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.directory = Path(tmp)
            name = 'skia-build-win-arm64-gpu-md-release'
            package, pin = ZipTests.package(self, name)
            wrapped = zip_bytes([(package.name, package.read_bytes())])
            artifact = {'name': name, 'id': 7, 'expired': False,
                        'size_in_bytes': len(wrapped),
                        'digest': 'sha256:' + hashlib.sha256(wrapped).hexdigest(),
                        'workflow_run': {'id': publisher.SOURCE_RUN, 'head_sha': publisher.SOURCE_SHA}}
            release = {'id': 42, 'tag_name': publisher.TAG, 'draft': False, 'prerelease': False}
            assets = [{'id': 5, 'name': 'existing-x64.zip', 'size': 10, 'digest': 'sha256:keep'}]
            api = mock.Mock()
            def pages(endpoint, key):
                if endpoint.endswith('/jobs'):
                    return source()[1]
                if endpoint.endswith('/artifacts'):
                    return [artifact]
                return list(assets)
            api.pages.side_effect = pages
            def json_api(endpoint):
                if endpoint.startswith('actions/'):
                    return source()[0]
                if endpoint.startswith('compare/'):
                    return source()[2]
                return release
            api.json.side_effect = json_api
            api.download.side_effect = lambda endpoint, output: output.write_bytes(wrapped)
            def upload(path):
                assets.append({'id': 6, 'name': path.name, 'size': pin[2], 'digest': 'sha256:' + pin[3]})
            api.upload.side_effect = upload
            with mock.patch.dict(publisher.MANIFEST, {name: pin}, clear=True), \
                 mock.patch.object(publisher, 'GitHub', return_value=api), \
                 mock.patch.dict(publisher.os.environ, {'GITHUB_REPOSITORY': publisher.REPOSITORY,
                                                      'GITHUB_REF': 'refs/heads/main'}), \
                 mock.patch('builtins.print'):
                publisher.publish(publisher.SOURCE_RUN, self.directory / 'dry')
                api.upload.assert_not_called()
                publisher.publish(publisher.SOURCE_RUN, self.directory / 'live', True)
                api.upload.assert_called_once()
                publisher.publish(publisher.SOURCE_RUN, self.directory / 'rerun', True)
                api.upload.assert_called_once()
            self.assertEqual('existing-x64.zip', assets[0]['name'])


if __name__ == '__main__':
    unittest.main()
