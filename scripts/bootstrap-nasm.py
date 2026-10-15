#!/usr/bin/env python3
"""Build a pinned NASM host tool privately; never install into the host OS."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/nasm'
BUILD = ROOT / 'build/nasm-host'
PREFIX = ROOT / '.deps/host-tools'
REVISION = 'cd37b81b320ead83ca5a6bbce5da0a6456663bc6'  # nasm-2.16.03


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    if not (SOURCE / '.git').exists():
        SOURCE.mkdir(parents=True, exist_ok=True)
        run('git', '-C', str(SOURCE), 'init', '-q')
        run('git', '-C', str(SOURCE), 'remote', 'add', 'origin',
            'https://github.com/netwide-assembler/nasm.git')
        run('git', '-C', str(SOURCE), 'fetch', '--depth=1', 'origin', REVISION)
        run('git', '-C', str(SOURCE), 'checkout', '--detach', REVISION)
    actual = subprocess.check_output(
        ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise RuntimeError('NASM checkout differs from pinned revision')
    BUILD.mkdir(parents=True, exist_ok=True)
    # The git tree's generated-file rules expect these out-of-tree directories.
    for path in SOURCE.rglob('*'):
        if path.is_dir() and '.git' not in path.relative_to(SOURCE).parts:
            (BUILD / path.relative_to(SOURCE)).mkdir(parents=True, exist_ok=True)
    if not (SOURCE / 'configure').exists():
        run('sh', 'autogen.sh', cwd=SOURCE)
    if not (BUILD / 'Makefile').exists():
        run(str(SOURCE / 'configure'), '--prefix=' + str(PREFIX), cwd=BUILD)
    run('make', '-j' + str(min(4, os.cpu_count() or 1)),
        'PERLFLAGS=-I. -I' + str(SOURCE / 'perllib') + ' -I' + str(SOURCE),
        'nasm', 'ndisasm', cwd=BUILD)
    # Install only executables; avoid documentation generation dependencies.
    for name in ('nasm', 'ndisasm'):
        destination = PREFIX / 'bin' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = (BUILD / name).read_bytes()
        if not destination.exists() or destination.read_bytes() != data:
            destination.write_bytes(data)
        destination.chmod(0o755)
    version = subprocess.check_output([str(PREFIX / 'bin/nasm'), '-v'], text=True).strip()
    (BUILD / 'build-report.json').write_text(json.dumps({
        'revision': actual, 'version': version, 'host_tool_only': True,
        'installed_to': str(PREFIX.relative_to(ROOT))}, indent=2) + '\n')
    print(version)


if __name__ == '__main__':
    main()
