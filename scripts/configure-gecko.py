#!/usr/bin/env python3
"""Reproducible first Gecko gate: cross-configure standalone SpiderMonkey for OpenOrbis.

This is deliberately separate from the working application package. Passing
configure is not a Rust runtime port, a browser engine build, or a hardware test.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
REVISION = '83cebcf5a522bf49667fd07084f04e8497de0eba'
SOURCE = ROOT / '.deps/gecko'
BUILD = ROOT / 'build/gecko-spidermonkey'
DIRECTORIES = ['.cargo', 'js', 'build', 'config', 'python', 'mozglue', 'memory', 'mfbt',
               'modules/fdlibm', 'modules/libpref', 'modules/zlib', 'third_party/fmt', 'third_party/gemmology',
               'third_party/xsimd', 'third_party/function2', 'third_party/python',
               'third_party/rust', 'testing', 'toolkit/components/glean']


def git(*args):
    subprocess.run(['git', '-C', str(SOURCE), *args], check=True)


def main():
    if not (SOURCE / '.git').exists():
        SOURCE.mkdir(parents=True, exist_ok=True)
        git('init', '-q')
        git('remote', 'add', 'origin', 'https://github.com/mozilla-firefox/firefox.git')
        git('-c', 'protocol.version=2', 'fetch', '--depth=1', '--filter=blob:none', 'origin', REVISION)
        git('sparse-checkout', 'init', '--cone')
        git('sparse-checkout', 'set', *DIRECTORIES)
        git('checkout', '--detach', REVISION)
    # Keep an existing sparse checkout in sync with newly required build inputs.
    # Cargo metadata reads every workspace member, even for standalone JS.
    # Fetch Rust crate roots without pulling unrelated C++ browser subtrees.
    files = subprocess.check_output(['git', '-C', str(SOURCE), 'ls-tree', '-r', '--name-only', REVISION], text=True).splitlines()
    crates = sorted({name.rsplit('/', 1)[0] for name in files
                     if name.endswith('/Cargo.toml') and not name.startswith('third_party/rust/')})
    git('sparse-checkout', 'set', *DIRECTORIES, 'xpcom/ds', *crates)
    actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise RuntimeError('Gecko source revision differs from the pinned SWGL revision')
    BUILD.mkdir(parents=True, exist_ok=True)
    if not (ROOT / '.deps/libcxx-orbis/lib/libc++.a').exists():
        subprocess.run([sys.executable, str(ROOT / 'scripts/build-libcxx.py')], check=True)
    if not (ROOT / '.deps/host-tools/bin/cbindgen').exists():
        subprocess.run(['cargo', 'install', 'cbindgen', '--version', '0.29.4', '--locked',
                        '--root', str(ROOT / '.deps/host-tools')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/sdk-overlay.py')], check=True)
    driver = ROOT / 'scripts/orbis-cc.py'
    subprocess.run([sys.executable, str(ROOT / 'scripts/build-rust.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/patch-rust-libc.py'),
                    str(SOURCE / 'third_party/rust/libc')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/patch-gecko.py'), str(SOURCE)], check=True)
    env = dict(os.environ, CC=str(driver), CXX=str(driver) + ' --cxx',
               RUSTC=str(ROOT / 'scripts/orbis-rustc.py'), RUSTC_BOOTSTRAP='1',
               RUST_LIBC_UNSTABLE_FREEBSD_VERSION='11',
               HOST_CC='clang', HOST_CXX='clang++', AR='llvm-ar', RANLIB='llvm-ranlib',
               CBINDGEN=str(ROOT / '.deps/host-tools/bin/cbindgen'),
               MOZBUILD_STATE_PATH=str(ROOT / '.deps/mozbuild'))
    command = [str(SOURCE / 'js/src/configure'), '--target=x86_64-orbis-freebsd12.0',
               '--disable-jemalloc', '--disable-shared-js', '--disable-jit', '--disable-profiling',
               '--disable-tests', '--without-intl-api', '--without-system-zlib', '--disable-bootstrap']
    output = BUILD / 'configure-output.log'
    with output.open('w') as log:
        result = subprocess.run(command, cwd=BUILD, env=env, stdout=log, stderr=subprocess.STDOUT)
    text = output.read_text()
    report = {'revision': actual, 'stage': 'SpiderMonkey cross-configuration',
              'result': result.returncode, 'gecko_in_package': False,
              'target': 'OpenOrbis SDK via FreeBSD compiler frontend (ABI adaptation still required)',
              'rust_std_missing': "can't find crate for `std`" in text,
              'rust_runtime': 'Private OpenOrbis-adapted sysroot; allocation/UTF-8 confirmed on hardware in OrbisFox 0.07 (not a complete runtime certification)',
              'cxx_runtime': 'Private libc++ 21.1.8; SDK ABI adaptation; hardware testing pending',
              'log': str(output.relative_to(ROOT))}
    (BUILD / 'configure-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
