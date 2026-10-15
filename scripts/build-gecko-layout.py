#!/usr/bin/env python3
"""Experimental full-engine build; no package, upload or hardware claims."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build/gecko-layout'


def build_errors(text):
    """Keep diagnostics, not Rust type names such as `pub enum DateError`."""
    diagnostic = re.compile(
        r'(^error(?:\[[A-Z][0-9]+\])?:(?!:)|(?:fatal )?error:(?!:)|^ERROR:'
        r'|\*\*\*.*Error [0-9]+|No rule to make target)')
    return [line.strip() for line in text.splitlines() if diagnostic.search(line)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 16:
        parser.error('--jobs must be between 1 and 16')
    subprocess.run([sys.executable, str(ROOT / 'scripts/build-media-codecs.py'), '--jobs', str(args.jobs)], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/configure-gecko-layout.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/fetch-layout-assets.py')], check=True)
    revision = (ROOT / 'build/rust/.abi-patch-revision').read_text()
    marker = BUILD / '.rust-sysroot-revision'
    if not marker.exists() or marker.read_text() != revision:
        for directory in ('x86_64-orbis-freebsd', 'release'):
            shutil.rmtree(BUILD / directory, ignore_errors=True)
        marker.write_text(revision)
    env = dict(os.environ, PATH=str(ROOT / '.deps/host-tools/bin') + os.pathsep + os.environ['PATH'])
    log = BUILD / 'build-output.log'
    with log.open('w') as output:
        result = subprocess.run(['make', '-j' + str(args.jobs)], cwd=BUILD, env=env,
                                stdout=output, stderr=subprocess.STDOUT)
    # This DSO is a link gate, not the deployed application. Keep its symbols
    # but discard multi-gigabyte DWARF; actual object inputs remain available.
    xul = BUILD / 'dist/bin/libxul.so'
    if result.returncode == 0 and xul.exists():
        with log.open('a') as output:
            stripped = subprocess.run(['llvm-strip', '--strip-debug', str(xul)],
                                      stdout=output, stderr=subprocess.STDOUT)
        if stripped.returncode:
            result = stripped
    text = log.read_text()
    errors = build_errors(text)
    report = {'stage': 'full Gecko cross-build', 'result': result.returncode,
              'log': str(log.relative_to(ROOT)),
              'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
              'errors': errors[:40], 'in_working_package': False,
              'full_engine_linked': result.returncode == 0 and (BUILD / 'dist/bin/libxul.so').exists(),
              'html_rendered': False, 'hardware_tested': False,
              'scope': 'Trusted offline bring-up only; no sandbox or website compatibility claim'}
    (BUILD / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
