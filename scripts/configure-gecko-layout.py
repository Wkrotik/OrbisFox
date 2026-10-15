#!/usr/bin/env python3
"""Experimental full-Gecko configure lane; never replaces the working package."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
REVISION = '83cebcf5a522bf49667fd07084f04e8497de0eba'
SOURCE = ROOT / '.deps/gecko-layout'
BUILD = ROOT / 'build/gecko-layout'
DIRECTORIES = '''.cargo accessible browser build caps chrome config devtools docshell dom
editor extensions gfx hal image intl ipc js layout media memory mfbt modules
mobile mozglue netwerk nsprpub other-licenses parser python security services servo
startupcache storage taskcluster testing third_party toolkit tools uriloader
widget xpcom xpfe'''.split()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def git(*args):
    return run('git', '-C', str(SOURCE), *args)


def write_changed(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != content:
        path.write_bytes(content)


def prepare_source():
    if not (SOURCE / '.git').exists():
        SOURCE.mkdir(parents=True, exist_ok=True)
        git('init', '-q')
        git('remote', 'add', 'origin', 'https://github.com/mozilla-firefox/firefox.git')
        # Independent checkout; reuse immutable objects, never the JS lane's files.
        objects = ROOT / '.deps/gecko/.git/objects'
        if objects.exists():
            write_changed(SOURCE / '.git/objects/info/alternates',
                          (str(objects) + '\n').encode())
        git('config', 'remote.origin.promisor', 'true')
        git('config', 'remote.origin.partialclonefilter', 'blob:none')
        git('-c', 'protocol.version=2', 'fetch', '--depth=1', '--filter=blob:none',
            'origin', REVISION)
        git('sparse-checkout', 'init', '--cone')
    files = subprocess.check_output(
        ['git', '-C', str(SOURCE), 'ls-tree', '-r', '--name-only', REVISION],
        text=True).splitlines()
    crates = sorted({name.rsplit('/', 1)[0] for name in files
                     if name.endswith('/Cargo.toml')
                     and not name.startswith('third_party/rust/')})
    git('sparse-checkout', 'set', *DIRECTORIES, *crates)
    git('checkout', '--detach', REVISION)
    actual = subprocess.check_output(
        ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise RuntimeError('Full Gecko checkout is not at the pinned revision')
    for source in (ROOT / 'gecko').rglob('*'):
        if source.is_file():
            write_changed(SOURCE / source.relative_to(ROOT / 'gecko'), source.read_bytes())
    run(sys.executable, str(ROOT / 'scripts/patch-gecko.py'), str(SOURCE))
    run(sys.executable, str(ROOT / 'scripts/patch-rust-libc.py'),
        str(SOURCE / 'third_party/rust/libc'))
    run(sys.executable, str(ROOT / 'scripts/patch-gecko-layout.py'), str(SOURCE))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    prepare_source()
    if args.prepare_only:
        return 0
    required = ['.deps/libcxx-orbis/lib/libc++.a',
                '.deps/rust-sysroot/lib/rustlib/x86_64-orbis-freebsd/lib',
                '.deps/host-tools/bin/cbindgen']
    for item in required:
        if not (ROOT / item).exists():
            raise RuntimeError('Build the existing runtime lane first: missing ' + item)
    if not (ROOT / '.deps/host-tools/bin/nasm').exists():
        run(sys.executable, str(ROOT / 'scripts/bootstrap-nasm.py'))
    run(sys.executable, str(ROOT / 'scripts/sdk-overlay.py'))
    BUILD.mkdir(parents=True, exist_ok=True)
    driver = ROOT / 'scripts/orbis-cc.py'
    env = dict(os.environ, PATH=str(ROOT / '.deps/host-tools/bin') + os.pathsep + os.environ['PATH'],
               CC=str(driver), CXX=str(ROOT / 'scripts/orbis-cxx.py'),
               # bindgen reads recorded flags, not the driver's implicit macros.
               CFLAGS=(os.environ.get('CFLAGS', '') + ' -D__ORBIS__ -D_GNU_SOURCE -D_BSD_SOURCE -mno-red-zone').strip(),
               CXXFLAGS=(os.environ.get('CXXFLAGS', '') + ' -D__ORBIS__ -D_GNU_SOURCE -D_BSD_SOURCE -mno-red-zone').strip(),
               BINDGEN_CFLAGS=(os.environ.get('BINDGEN_CFLAGS', '') + ' -D__ORBIS__ -D_GNU_SOURCE -D_BSD_SOURCE').strip(),
               # Private static runtime internals must not resolve through another
               # experimental DSO. SDK DNS configuration is a real SceNet import.
               LDFLAGS=(os.environ.get('LDFLAGS', '') +
                        ' -Wl,--exclude-libs,libc.a:libc++.a:libc++abi.a:libunwind.a -lSceNet').strip(),
               RUSTC=str(ROOT / 'scripts/orbis-rustc.py'), RUSTC_BOOTSTRAP='1',
               RUST_LIBC_UNSTABLE_FREEBSD_VERSION='11',
               HOST_CC='clang', HOST_CXX='clang++', AR='llvm-ar', RANLIB='llvm-ranlib',
               CBINDGEN=str(ROOT / '.deps/host-tools/bin/cbindgen'),
               MOZBUILD_STATE_PATH=str(ROOT / '.deps/mozbuild'))
    command = [str(SOURCE / 'configure'), '--target=x86_64-orbis-freebsd12.0',
               '--enable-application=orbisfox', '--enable-default-toolkit=cairo-orbis',
               '--disable-jemalloc', '--disable-profiling',
               '--disable-tests', '--disable-bootstrap', '--disable-updater',
               '--disable-crashreporter', '--disable-webrtc', '--disable-accessibility',
               '--disable-necko-wifi', '--disable-webdriver', '--disable-audio-backends',
               '--disable-sandbox', '--without-wasm-sandboxed-libraries',
               '--without-system-zlib']
    log = BUILD / 'configure-output.log'
    with log.open('w') as output:
        result = subprocess.run(command, cwd=BUILD, env=env,
                                stdout=output, stderr=subprocess.STDOUT)
    text = log.read_text()
    errors = [line.strip() for line in text.splitlines()
              if 'ERROR:' in line or line.startswith(('FileNotFoundError:',
                  'ValueError:', 'Exception:', 'ConfigureError:', 'RuntimeError:',
                  'mozbuild.configure.options.InvalidOptionError:'))
              or 'FATAL ERROR PROCESSING MOZBUILD FILE' in line
              or 'Error processing test manifest' in line]
    report = {'revision': REVISION, 'stage': 'full Gecko cross-configuration',
              'result': result.returncode, 'command': command,
              'log': str(log.relative_to(ROOT)),
              'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
              'errors': errors[-8:], 'failure_tail': text.splitlines()[-30:] if result.returncode else [],
              'build_backend_generated': result.returncode == 0 and (BUILD / 'Makefile').exists(),
              'in_working_package': False,
              'html_rendered': False, 'hardware_tested': False,
              'sandbox_disabled': True,
              'scope': 'Trusted offline bring-up only; not safe for untrusted websites'}
    (BUILD / 'configure-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
