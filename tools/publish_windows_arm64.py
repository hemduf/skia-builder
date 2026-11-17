"""Publish only the four reviewed Windows ARM64 packages to existing M153.

No build/tag creation, asset replacement or artifact code execution is performed.
The reviewed manifest intentionally permits one source run; another run requires
reviewing its binaries and updating these pins before publication.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


REPOSITORY = 'hemduf/skia-builder'
TAG = 'chrome/m153'
SOURCE_RUN = 44118742917
SOURCE_SHA = '61fdc99dfffb4b9f461ed2fbfbe216dc2d9d1bec'
MANIFEST = {
    'skia-build-win-arm64-gpu-debug': (
        'MT', 'Debug', 329500055,
        '40e9a5164326a12d69cc23a9562618acaeff275cfb286e26fe839f6c88877c7e'),
    'skia-build-win-arm64-gpu-md-debug': (
        'MD', 'Debug', 323094390,
        '1617b77408ae4237fa93895966aca937644629f5ab6d3f70d25693ede08baddd'),
    'skia-build-win-arm64-gpu-md-release': (
        'MD', 'Release', 39491522,
        'c6f7add61910d606abeccfa6162f3c2c8ef37d89996fbe54299d95beab8a373e'),
    'skia-build-win-arm64-gpu-release': (
        'MT', 'Release', 40806537,
        '1cbd65a18d3e39e376a3c2ceb4ec0598f001b22ab3b076b1d3a749ce4f95f3ff'),
}
LIBRARIES = ('skia.lib', 'skottie.lib', 'skparagraph.lib', 'sksg.lib',
             'skshaper.lib', 'skunicode_core.lib', 'skunicode_icu.lib',
             'svg.lib', 'dawn_combined.lib')
MAX_ZIP_BYTES = 1024 ** 3
MAX_PAYLOAD_BYTES = 8 * 1024 ** 3


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_source(run, jobs, comparison, run_id):
    require(run_id == SOURCE_RUN and run.get('id') == SOURCE_RUN,
            'Only the reviewed source run is permitted')
    require(run.get('head_sha') == SOURCE_SHA, 'Source SHA differs from reviewed run')
    require(run.get('repository', {}).get('full_name') == REPOSITORY and
            run.get('head_repository', {}).get('full_name') == REPOSITORY,
            'Source repository mismatch')
    require(run.get('event') == 'workflow_dispatch' and
            run.get('path') == '.github/workflows/build-skia.yml' and
            run.get('status') == 'completed' and run.get('run_attempt') == 1,
            'Source must be the completed, reviewed manual build attempt')
    require(comparison.get('status') in ('ahead', 'identical') and
            comparison.get('merge_base_commit', {}).get('sha') == SOURCE_SHA,
            'Source SHA must be reachable from main')
    # This run has unrelated cancelled macOS entries. Qualify every Windows job,
    # not the overall matrix conclusion, and never treat skipped builds as green.
    for name, (crt, config, _, _) in MANIFEST.items():
        expected = f'build-skia (windows-11-arm, win, gpu, arm64, {config}, {crt})'
        matches = [job for job in jobs if job.get('name') == expected]
        require(len(matches) == 1, f'Missing or duplicate source job: {expected}')
        job = matches[0]
        require(job.get('status') == 'completed' and job.get('conclusion') == 'success',
                f'Unsuccessful source job: {expected}')
        for step in (f'Build Skia ({config})', 'Validate Windows ARM64 package',
                     'Package binaries', 'Upload artifact'):
            found = [s for s in job.get('steps', []) if s.get('name') == step]
            require(len(found) == 1 and found[0].get('conclusion') == 'success',
                    f'Missing successful step: {expected}: {step}')
    for job in jobs:
        if ', win,' in job.get('name', ''):
            require(job.get('status') == 'completed' and job.get('conclusion') == 'success',
                    'A Windows source job did not succeed')


def select_artifacts(artifacts):
    selected = {}
    for name in MANIFEST:
        matches = [a for a in artifacts if a.get('name') == name]
        require(len(matches) == 1, f'Missing or duplicate artifact: {name}')
        artifact = matches[0]
        source = artifact.get('workflow_run', {})
        require(source.get('id') == SOURCE_RUN and source.get('head_sha') == SOURCE_SHA,
                f'Artifact source mismatch: {name}')
        require(not artifact.get('expired', True), f'Artifact expired: {name}')
        require(isinstance(artifact.get('id'), int) and artifact['id'] > 0,
                'Invalid artifact ID')
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', '')),
                'Artifact requires an API SHA256 digest')
        require(0 < artifact.get('size_in_bytes', 0) <= MAX_ZIP_BYTES,
                'Artifact wrapper size is out of bounds')
        selected[name] = artifact
    return selected


def safe_members(archive):
    infos = archive.infolist()
    require(len(infos) <= 10000, 'Too many ZIP members')
    names = set()
    total = 0
    for info in infos:
        name = info.filename
        parts = PurePosixPath(name).parts
        require(name and '\\' not in name and ':' not in name and
                not name.startswith('/') and
                all(p not in ('', '.', '..') for p in name.rstrip('/').split('/')) and
                all(ord(c) >= 32 for c in name),
                f'Unsafe ZIP member: {name}')
        require(parts and '\x00' not in name and name not in names,
                'Duplicate or invalid ZIP member')
        require(not stat.S_ISLNK(info.external_attr >> 16) and
                not info.flag_bits & 1 and
                info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                f'Unsupported ZIP member: {name}')
        names.add(name)
        total += info.file_size
        require(total <= MAX_PAYLOAD_BYTES, 'ZIP payload is too large')
    return infos


def unwrap_artifact(wrapper, artifact, output_dir):
    name = artifact['name']
    require(name in MANIFEST, 'Unreviewed artifact name')
    require(wrapper.stat().st_size == artifact['size_in_bytes'] and
            sha256(wrapper) == artifact['digest'].removeprefix('sha256:'),
            'Artifact wrapper digest/size mismatch')
    with zipfile.ZipFile(wrapper) as archive:
        infos = safe_members(archive)
        require(len(infos) == 1 and infos[0].filename == name + '.zip' and
                0 < infos[0].file_size <= MAX_ZIP_BYTES,
                'Artifact wrapper must contain exactly its named package ZIP')
        output = output_dir / (name + '.zip')
        with archive.open(infos[0]) as source, output.open('xb') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
    return output


def _read_exact(stream, length):
    value = stream.read(length)
    require(len(value) == length, 'Truncated COFF archive')
    return value


def _discard(stream, length):
    while length:
        block = _read_exact(stream, min(length, 1024 * 1024))
        length -= len(block)


def validate_coff_archive(stream):
    require(_read_exact(stream, 8) == b'!<arch>\n', 'Expected COFF library archive')
    members = 0
    while True:
        header = stream.read(60)
        if not header:
            break
        require(len(header) == 60 and header[58:] == b'`\n', 'Malformed archive member')
        require(re.fullmatch(rb' *[0-9]+ *', header[48:58]), 'Invalid archive member size')
        size = int(header[48:58])
        name = header[:16].strip()
        if name in (b'/', b'//', b'/SYM64/'):
            _discard(stream, size)
        else:
            require(size >= 8, 'COFF member is too small')
            prefix = _read_exact(stream, 8)
            # COFF bigobj and import headers place Machine at offset 6.
            offset = 6 if prefix[:4] == b'\x00\x00\xff\xff' else 0
            require(struct.unpack_from('<H', prefix, offset)[0] == 0xAA64,
                    'Non-ARM64 COFF archive member')
            members += 1
            _discard(stream, size - 8)
        if size & 1:
            require(_read_exact(stream, 1) == b'\n', 'Invalid archive alignment')
    require(members > 0, 'COFF archive has no object members')


def validate_package(package, name):
    require(name in MANIFEST and package.name == name + '.zip', 'Unreviewed package name')
    crt, config, expected_size, expected_sha = MANIFEST[name]
    require(package.stat().st_size == expected_size and sha256(package) == expected_sha,
            'Inner package differs from the reviewed binary manifest')
    variant = 'win-gpu-md' if crt == 'MD' else 'win-gpu'
    library_dir = f'build/{variant}/lib/{config}/arm64/'
    summary = f'build/{variant}/lib/gn_args.txt'
    required = {'build/include/include/core/SkCanvas.h', 'build/share/icudtl.dat', summary}
    required.update(library_dir + lib for lib in LIBRARIES)
    with zipfile.ZipFile(package) as archive:
        infos = safe_members(archive)
        files = {i.filename: i for i in infos if not i.is_dir()}
        require(required <= files.keys(), 'Package lacks required headers/libraries/ICU/metadata')
        require(all(files[p].file_size > 0 for p in required), 'Empty required package member')
        for member in infos:
            allowed = (member.filename.startswith('build/include/') or
                       member.filename in ('build/share/', 'build/share/icudtl.dat',
                                           f'build/{variant}/', f'build/{variant}/lib/',
                                           f'build/{variant}/lib/{config}/', summary) or
                       member.filename.startswith(library_dir))
            require(allowed, f'Unexpected package path: {member.filename}')
            if member.filename.endswith('.lib'):
                require(member.filename.startswith(library_dir), 'Wrong library architecture/path')
                with archive.open(member) as stream:
                    validate_coff_archive(stream)
        require(files[summary].file_size <= 64 * 1024, 'Oversized package metadata')
        metadata = archive.read(summary).decode('utf-8')
        for pattern in (rf'^Configuration: {config}\s*$', r'^Architectures: arm64\s*$',
                        r'^Variant: gpu\s*$', r'^target_cpu = "arm64"\s*$',
                        rf'^crt = "{crt}"\s*$', r'^skia_use_gl = true\s*$'):
            require(len(re.findall(pattern, metadata, re.MULTILINE)) == 1,
                    f'Package build metadata mismatch: {pattern}')
    return {'name': package.name, 'size': expected_size, 'sha256': expected_sha,
            'source_run': SOURCE_RUN, 'source_sha': SOURCE_SHA}


def upload_plan(packages, assets):
    plan = []
    for package in packages:
        matches = [a for a in assets if a.get('name') == package['name']]
        require(len(matches) <= 1, 'Duplicate release asset names')
        if matches:
            asset = matches[0]
            require(asset.get('size') == package['size'] and
                    asset.get('digest') == 'sha256:' + package['sha256'],
                    f'Conflicting existing asset; refusing replacement: {package["name"]}')
        else:
            plan.append(package['name'])
    return plan


class GitHub:
    def json(self, endpoint):
        return json.loads(subprocess.check_output(
            ['gh', 'api', '--hostname', 'github.com', f'repos/{REPOSITORY}/{endpoint}'], text=True))

    def pages(self, endpoint, key):
        result = []
        for page in range(1, 101):
            data = self.json(f'{endpoint}?per_page=100&page={page}')
            entries = data[key] if key else data
            result.extend(entries)
            if len(entries) < 100:
                return result
        raise ValueError('API pagination limit exceeded')

    def download(self, endpoint, output):
        with output.open('xb') as stream:
            subprocess.run(['gh', 'api', '--hostname', 'github.com',
                            '-H', 'Accept: application/octet-stream',
                            f'repos/{REPOSITORY}/{endpoint}'], stdout=stream, check=True)

    def upload(self, package):
        subprocess.run(['gh', 'release', 'upload', TAG, str(package),
                        '--repo', 'github.com/' + REPOSITORY], check=True)


def publish(run_id, directory, do_publish=False):
    require(run_id == SOURCE_RUN, 'Only the reviewed source run is permitted')
    if do_publish:
        require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
                os.environ.get('GITHUB_REF') == 'refs/heads/main',
                'Publication must run from the repository main workflow')
    api = GitHub()
    run = api.json(f'actions/runs/{run_id}')
    jobs = api.pages(f'actions/runs/{run_id}/attempts/1/jobs', 'jobs')
    comparison = api.json(f'compare/{SOURCE_SHA}...main')
    validate_source(run, jobs, comparison, run_id)
    selected = select_artifacts(api.pages(f'actions/runs/{run_id}/artifacts', 'artifacts'))
    release = api.json('releases/tags/chrome%2Fm153')
    require(release.get('tag_name') == TAG and not release.get('draft') and
            not release.get('prerelease') and isinstance(release.get('id'), int),
            'An existing public stable M153 release is required')
    release_id = release['id']
    assets = api.pages(f'releases/{release_id}/assets', None)
    directory.mkdir(parents=True, exist_ok=False)
    packages = []
    for name, artifact in selected.items():
        wrapper = directory / (name + '-wrapper.zip')
        api.download(f'actions/artifacts/{artifact["id"]}/zip', wrapper)
        inner = unwrap_artifact(wrapper, artifact, directory)
        packages.append(validate_package(inner, name))
        wrapper.unlink()
    plan = upload_plan(packages, assets)
    report = {'dry_run': not do_publish, 'release': TAG, 'packages': packages,
              'missing_assets': plan, 'source_overall_conclusion': run.get('conclusion'),
              'qualification': 'All Windows jobs and ARM64 build/package validations succeeded'}
    (directory / 'publication-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if do_publish:
        # Recheck immediately before mutation. gh's default upload refuses name
        # collisions, including a publisher racing this verified plan.
        assets = api.pages(f'releases/{release_id}/assets', None)
        for name in upload_plan(packages, assets):
            api.upload(directory / name)
        after = api.pages(f'releases/{release_id}/assets', None)
        require(not upload_plan(packages, after), 'Post-upload verification failed')
        previous = {a['name']: (a['id'], a['size'], a.get('digest')) for a in assets
                    if a['name'] not in {p['name'] for p in packages}}
        current = {a['name']: (a['id'], a['size'], a.get('digest')) for a in after
                   if a['name'] not in {p['name'] for p in packages}}
        require(previous == current, 'Unrelated release assets changed during publication')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--publish', action='store_true', help='Default is verification only')
    args = parser.parse_args()
    publish(args.run_id, args.directory, args.publish)
