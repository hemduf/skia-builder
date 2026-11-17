"""Reject wrong-architecture or GL-incomplete Windows ARM64 packages.

This checks archive metadata and defined symbols, not GPU rendering or host support.
"""

import argparse
import re
import subprocess
from pathlib import Path


REQUIRED_LIBRARIES = (
    'skia.lib', 'skottie.lib', 'sksg.lib', 'skshaper.lib', 'skparagraph.lib',
    'svg.lib', 'skunicode_core.lib', 'skunicode_icu.lib', 'dawn_combined.lib',
)


def validate_machine_headers(output):
    machines = re.findall(r'^\s*Machine:\s*(.+)$', output, re.MULTILINE)
    if not machines:
        raise ValueError('No COFF machine headers found')
    if any(not re.fullmatch(r'IMAGE_FILE_MACHINE_ARM64\s+\(0xAA64\)', m)
           for m in machines):
        raise ValueError('Non-ARM64 COFF member: ' + ', '.join(sorted(set(machines))))


def validate_gl_symbols(output):
    for symbol in ('GrGLMakeAssembledInterface', 'GrDirectContexts::MakeGL'):
        if symbol not in output:
            raise ValueError(f'Missing defined Ganesh/OpenGL symbol: {symbol}')


def validate_package(directory):
    for name in REQUIRED_LIBRARIES:
        if not (directory / name).is_file():
            raise ValueError(f'Missing required library: {directory / name}')
    # Inspect all members, not just the first: a mixed x64/ARM64 archive is invalid.
    for archive in sorted(directory.glob('*.lib')):
        result = subprocess.run(['llvm-readobj', '--file-headers', str(archive)],
                                check=True, text=True, capture_output=True)
        validate_machine_headers(result.stdout)
        print(f'{archive.name}: ARM64 COFF members verified')
    result = subprocess.run(
        ['llvm-nm', '--extern-only', '--defined-only', '--demangle', str(directory / 'skia.lib')],
        check=True, text=True, capture_output=True)
    validate_gl_symbols(result.stdout)
    print('Ganesh/OpenGL entry points verified (runtime rendering not tested)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    validate_package(parser.parse_args().directory)
