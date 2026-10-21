#!/usr/bin/env python3
"""Experimental full-Gecko configure lane; never replaces the working package."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import shlex
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


def prepare_source(sdk='openorbis'):
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
    abi = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
    abi['prepare_libc'](SOURCE, native_sdk=(sdk == 'homebrew'))
    if sdk == 'homebrew':
        abi['patch_rust_detection'](SOURCE)
        abi['patch_allocator_fallback'](SOURCE)
        abi['patch_native_ffi'](SOURCE)
        abi['patch_maybe_constexpr'](SOURCE)
        abi['patch_native_js_thread'](SOURCE)
        abi['patch_native_js_stack'](SOURCE)
        abi['patch_native_signal_stack'](SOURCE)
        abi['patch_native_dav1d_headers'](SOURCE)
        abi['patch_native_ffvpx_math'](SOURCE)
        abi['patch_native_engine_libraries'](SOURCE)
        abi['patch_native_platform_capabilities'](SOURCE)
        abi['patch_native_demangling'](SOURCE)
        abi['patch_native_file_handle_clone'](SOURCE)
        abi['patch_native_file_handle_truthiness'](SOURCE)
        abi['patch_native_descriptor_shuffle'](SOURCE)
        abi['patch_native_shared_memory_errors'](SOURCE)
    run(sys.executable, str(ROOT / 'scripts/patch-gecko-layout.py'), str(SOURCE))


def native_bindgen_flags(root=ROOT):
    root = Path(root)
    sdk = root / '.deps/ps4-homebrew-sdk-v0.2.1/target'
    resource = Path(subprocess.check_output([
        str(sdk.parent / 'bin/orbis-clang'), '-print-resource-dir'], text=True).strip()).resolve()
    for header in ('stddef.h', 'emmintrin.h'):
        if not (resource / 'include' / header).is_file():
            raise RuntimeError('Native bindgen needs genuine LLVM resource headers: ' + header)
    # libclang never executes the SDK shell driver's configuration. Reproduce
    # the target/sysroot explicitly: libc++ wrappers, LLVM builtin headers,
    # then BSD C headers. The SDK's old stddef.h lacks LLVM's max_align_t.
    return ['--target=x86_64-scei-ps4', '--sysroot=' + str(sdk),
            '-resource-dir', str(resource),
            '-DORBISFOX_HOMEBREW_SDK=1', '-nostdinc++',
            '-isystem', str(root / '.deps/libcxx-homebrew/include/c++/v1'),
            '-isystem', str(root / '.deps/homebrew-service-headers/include'),
            '-idirafter', str(sdk / 'include')]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--sdk', choices=('openorbis', 'homebrew'),
                        default=os.environ.get('ORBISFOX_SDK', 'openorbis'))
    parser.add_argument('--mesa', action='store_true', help='Compile the default-off Mesa/WebRender experiment')
    args = parser.parse_args()
    if args.sdk not in ('openorbis', 'homebrew'):
        parser.error('Unknown ORBISFOX_SDK: ' + args.sdk)
    prepare_source(args.sdk)
    if args.prepare_only:
        return 0
    native_sdk = args.sdk == 'homebrew'
    required = (['.deps/libcxx-homebrew/lib/libc++.a',
                 '.deps/rust-homebrew-sysroot/lib/rustlib/x86_64-scei-ps4/lib']
                if native_sdk else ['.deps/libcxx-orbis/lib/libc++.a',
                                    '.deps/rust-sysroot/lib/rustlib/x86_64-orbis-freebsd/lib'])
    required += ['.deps/host-tools/bin/cbindgen']
    sdk_identity = None
    service_headers = None
    if native_sdk:
        service_headers = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))['verify']()
        sdk = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-sdk.py'))['verify_sdk']()
        sdk_identity = {key: sdk[key] for key in ('version', 'revision', 'archive_sha256')}
        for producer in ('libcxx-homebrew', 'rust-homebrew'):
            report = json.loads((ROOT / 'build' / producer / 'build-report.json').read_text())
            if report['result'] != 0 or any(report['sdk'].get(key) != value for key, value in sdk_identity.items()):
                raise RuntimeError('Rebuild the selected native SDK runtime: ' + producer)
    for item in required:
        if not (ROOT / item).exists():
            raise RuntimeError('Build the existing runtime lane first: missing ' + item)
    if not (ROOT / '.deps/host-tools/bin/nasm').exists():
        run(sys.executable, str(ROOT / 'scripts/bootstrap-nasm.py'))
    if not native_sdk:
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
    env['ORBISFOX_SDK'] = args.sdk
    if native_sdk:
        declarations = shlex.join(['-isystem', str(ROOT / '.deps/homebrew-service-headers/include')])
        env['CFLAGS'] += ' ' + declarations
        env['CXXFLAGS'] += ' ' + declarations
        env['BINDGEN_CFLAGS'] += ' ' + shlex.join(native_bindgen_flags())
    command = [str(SOURCE / 'configure'),
               '--target=x86_64-orbis-freebsd9.0' if native_sdk else '--target=x86_64-orbis-freebsd12.0',
               '--enable-application=orbisfox', '--enable-default-toolkit=cairo-orbis',
               '--disable-jemalloc', '--disable-profiling',
               '--disable-tests', '--disable-bootstrap', '--disable-updater',
               '--disable-crashreporter', '--disable-webrtc', '--disable-accessibility',
               '--disable-necko-wifi', '--disable-webdriver', '--disable-audio-backends',
               '--disable-sandbox', '--without-wasm-sandboxed-libraries',
               '--without-system-zlib',
               '--enable-orbis-homebrew-sdk' if native_sdk else '--disable-orbis-homebrew-sdk',
               '--enable-orbis-mesa' if args.mesa else '--disable-orbis-mesa']
    if native_sdk:
        # Retain ABI caches; generic FreeBSD otherwise defaults the interpreter to -O1.
        command.extend(['--disable-cargo-incremental', '--enable-optimize=-O2'])
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
              'experimental_mesa': args.mesa, 'sdk': args.sdk,
              'sdk_identity': sdk_identity, 'service_headers': service_headers,
              'result': result.returncode, 'command': command,
              'optimization_flags': json.loads((BUILD / 'config.status.json').read_text())['substs']['MOZ_OPTIMIZE_FLAGS'] if result.returncode == 0 else [],
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
