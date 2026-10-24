#!/usr/bin/env python3
"""Experimental full-engine build; no package, upload or hardware claims."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
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


def prerequisite_commands(sdk, mesa, jobs):
    if sdk not in ('openorbis', 'homebrew'):
        raise RuntimeError('Unknown ORBISFOX_SDK: ' + sdk)
    if sdk == 'homebrew' and mesa:
        raise RuntimeError('Native SDK Mesa dependency migration is incomplete; '
                           'do not link the old-SDK GPU archives into a native engine')
    scripts = []
    if sdk == 'homebrew':
        scripts += [('build-homebrew-libcxx.py', []), ('build-homebrew-rust.py', [])]
    scripts += [('build-media-codecs.py', ['--sdk', sdk])]
    if mesa:
        scripts += [('build-orbis-mesa.py', [])]
    commands = ([[sys.executable, str(ROOT / 'scripts/fetch-homebrew-service-headers.py')]]
                if sdk == 'homebrew' else [])
    return commands + [[sys.executable, str(ROOT / 'scripts' / name), '--jobs', str(jobs), *options]
                       for name, options in scripts]


def require_build_sdk(sdk, build=BUILD):
    report = build / 'configure-report.json'
    if report.exists():
        existing = json.loads(report.read_text()).get('sdk', 'openorbis')
        if existing != sdk:
            raise RuntimeError('Object tree SDK mismatch: ' + existing + ' != ' + sdk +
                               '; preserve its thin-archive inputs and explicitly retire it before switching')
    elif (build / 'config.status').exists():
        raise RuntimeError('Object tree has no recorded SDK identity; inspect it before rebuilding')


def native_rust_revision(root=ROOT):
    report = json.loads((root / 'build/rust-homebrew/build-report.json').read_text())
    sdk = runpy.run_path(str(root / 'scripts/fetch-homebrew-sdk.py'))['verify_sdk']()
    if report['result'] != 0 or report['target'] != 'x86_64-scei-ps4' or any(
            report['sdk'].get(key) != sdk[key] for key in ('version', 'revision', 'archive_sha256')):
        raise RuntimeError('Native Rust runtime SDK identity mismatch')
    archive = root / 'build/rust-homebrew/liborbisfox.a'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != report['probe_archive_sha256']:
        raise RuntimeError('Native Rust runtime probe archive changed')
    return report['abi_revision']


def prepare_rust_cache(sdk, revision, build=BUILD):
    marker = build / '.rust-sysroot-revision'
    if marker.exists() and marker.read_text() == revision:
        return
    if sdk == 'homebrew':
        # Never delete a native object/member tree just to invalidate Cargo.
        if any((build / name).exists() for name in ('x86_64-scei-ps4', 'release')):
            raise RuntimeError('Native Rust cache ABI changed; preserve/archive owned inputs before rebuilding')
    else:
        for directory in ('x86_64-orbis-freebsd', 'release'):
            shutil.rmtree(build / directory, ignore_errors=True)
    marker.write_text(revision)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--mesa', action='store_true', help='Explicit experimental native Mesa build')
    parser.add_argument('--sdk', choices=('openorbis', 'homebrew'),
                        default=os.environ.get('ORBISFOX_SDK', 'openorbis'))
    parser.add_argument('--portable-baseline', action='store_true')
    args = parser.parse_args()
    if args.portable_baseline and args.sdk != 'homebrew':
        parser.error('--portable-baseline requires --sdk homebrew')
    if not 1 <= args.jobs <= 16:
        parser.error('--jobs must be between 1 and 16')
    commands = prerequisite_commands(args.sdk, args.mesa, args.jobs)
    require_build_sdk(args.sdk)
    env = dict(os.environ, ORBISFOX_SDK=args.sdk,
               PATH=str(ROOT / '.deps/host-tools/bin') + os.pathsep + os.environ['PATH'])
    for command in commands:
        subprocess.run(command, env=env, check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/configure-gecko-layout.py'), '--sdk', args.sdk] +
                   (['--mesa'] if args.mesa else []) +
                   (['--portable-baseline'] if args.portable_baseline else []), env=env, check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/fetch-layout-assets.py')], env=env, check=True)
    revision = (native_rust_revision() if args.sdk == 'homebrew' else
                (ROOT / 'build/rust/.abi-patch-revision').read_text())
    prepare_rust_cache(args.sdk, revision)
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
              'experimental_mesa': args.mesa, 'sdk': args.sdk,
              'portable_baseline': args.portable_baseline,
              'configure_report_sha256': hashlib.sha256((BUILD / 'configure-report.json').read_bytes()).hexdigest(),
              'rust_abi_revision': revision,
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
