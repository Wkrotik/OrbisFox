#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a separate native-SDK Rust standard library and existing runtime probe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent
TARGET = 'x86_64-scei-ps4'
BUILD = ROOT / 'build/rust-homebrew'
SYSROOT = ROOT / '.deps/rust-homebrew-sysroot'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error('--jobs must be 1..32')
    sdk = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-sdk.py'))['verify_sdk']()
    library = runpy.run_path(str(ROOT / 'scripts/bootstrap-homebrew-rust.py'))['bootstrap']()
    revision = hashlib.sha256(b''.join(p.read_bytes() for p in (
        ROOT / 'scripts/bootstrap-homebrew-rust.py', ROOT / 'scripts/homebrew-rustc.py',
        ROOT / 'targets/x86_64-scei-ps4.json'))).hexdigest()
    BUILD.mkdir(parents=True, exist_ok=True)
    # Distinct ABI revision directories avoid both stale vendored build-script
    # caches and deletion of another build's archive member inputs.
    objects = BUILD / revision[:16]
    env = dict(os.environ, RUSTC=str(ROOT / 'scripts/homebrew-rustc.py'),
               RUSTC_BOOTSTRAP='1', CARGO_TARGET_DIR=str(objects), ORBISFOX_SDK='homebrew')
    command = ['cargo', 'build', '-j', str(args.jobs), '-Zjson-target-spec',
               '-Zbuild-std=std,panic_abort', '--release',
               '--target', str(ROOT / 'targets/x86_64-scei-ps4.json'),
               '--manifest-path', str(ROOT / 'rust/runtime-probe/Cargo.toml'),
               '--config', 'source.crates-io.replace-with="rust-source"',
               '--config', f'source.rust-source.directory="{library / "vendor"}"']
    report = {'sdk': sdk, 'target': TARGET, 'abi_revision': revision, 'started_ns': time.time_ns(),
              'commands': [command], 'result': None, 'console_tested': False}
    try:
        subprocess.run(command, env=env, check=True)
        command = command.copy()
        command[1] = 'rustc'
        command += ['--crate-type=rlib']
        report['commands'].append(command)
        subprocess.run(command, env=env, check=True)
        built = objects / TARGET / 'release'
        rlib = built / 'liborbisfox_runtime_probe.rlib'
        members = subprocess.check_output(['llvm-ar', 't', rlib], text=True).splitlines()
        members = [name for name in members if name.endswith('.o')]
        if not members:
            raise RuntimeError('Native Rust probe has no real code objects')
        probe = objects / 'probe-objects'
        probe.mkdir(exist_ok=True)
        subprocess.run(['llvm-ar', 'x', rlib, *members], cwd=probe, check=True)
        archive = BUILD / 'liborbisfox.a'
        archive.unlink(missing_ok=True)
        subprocess.run(['llvm-ar', 'rcs', archive, *[probe / name for name in members]], check=True)
        destination = SYSROOT / 'lib/rustlib' / TARGET / 'lib'
        destination.mkdir(parents=True, exist_ok=True)
        for path in (built / 'deps').iterdir():
            if path.suffix in ('.rlib', '.rmeta') and not path.name.startswith('liborbisfox_runtime_probe'):
                shutil.copy2(path, destination / path.name)
        report['result'] = 0
        report['probe_archive_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        report['staticlib'] = str(built / 'liborbisfox_runtime_probe.a')
        report['objects'] = str(objects)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        report['result'] = getattr(error, 'returncode', 1)
        report['error'] = str(error)
        raise
    finally:
        report['finished_ns'] = time.time_ns()
        (BUILD / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
