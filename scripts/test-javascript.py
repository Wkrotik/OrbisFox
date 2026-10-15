#!/usr/bin/env python3
"""Build/run the real standalone SpiderMonkey host embedding (not a JS substitute)."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build/gecko-host'
REVISION = '83cebcf5a522bf49667fd07084f04e8497de0eba'

def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CC='clang', CXX='clang++', HOST_CC='clang', HOST_CXX='clang++',
               AR='llvm-ar', RANLIB='llvm-ranlib',
               CBINDGEN=str(ROOT / '.deps/host-tools/bin/cbindgen'),
               MOZBUILD_STATE_PATH=str(ROOT / '.deps/mozbuild'))
    env.pop('RUSTC', None)
    if not (BUILD / 'config.status').exists():
        with (BUILD / 'configure-output.log').open('w') as log:
            subprocess.run([str(ROOT / '.deps/gecko/js/src/configure'), '--disable-jemalloc',
                '--disable-shared-js', '--disable-jit', '--disable-profiling', '--disable-tests',
                '--without-intl-api', '--without-system-zlib', '--disable-bootstrap'],
                cwd=BUILD, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (BUILD / 'build-output.log').open('w') as log:
        subprocess.run(['make', '-j' + os.environ.get('ORBISFOX_HOST_JOBS', '4')],
                       cwd=BUILD, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    response = BUILD / 'js/src/shell/js.list'
    objects = [(response.parent / name).resolve() for name in response.read_text().splitlines()
               if name and not name.startswith('Unified_cpp_js_src_shell') and '/editline/' not in name]
    support = BUILD / 'liborbisfox-gecko-support.a'
    support.unlink(missing_ok=True)
    subprocess.run(['llvm-ar', 'rcs', str(support), *map(str, objects)], check=True)
    rust_archives = list(BUILD.glob('*/release/libjsrust.a'))
    if len(rust_archives) != 1:
        raise RuntimeError('Expected exactly one host jsrust archive')
    executable = ROOT / 'build/js-canvas-test'
    sources = ['src/js_canvas.cpp', 'src/surface.cpp', 'tests/js_canvas_test.cpp']
    command = ['clang++', '-std=c++20', '-O1', '-g', '-fno-rtti', '-fno-exceptions',
               '-fno-sized-deallocation', '-fno-aligned-new', '-fsanitize=address,undefined',
               '-fno-omit-frame-pointer', '-Iinclude', '-isystem', str(BUILD / 'dist/include'),
               '-include', str(BUILD / 'js/src/js-confdefs.h'), *sources,
               str(BUILD / 'js/src/build/libjs_static.a'), str(support), str(rust_archives[0]),
               '-lpthread', '-ldl', '-lm', '-o', str(executable)]
    report = ROOT / 'build/javascript-host-report.json'
    report.unlink(missing_ok=True)
    subprocess.run(command, cwd=ROOT, check=True)
    subprocess.run([str(executable)], cwd=ROOT, check=True)
    audited_files = sources + ['include/orbisfox/js_canvas.h', 'include/orbisfox/surface.h',
                               'assets/playground.js', 'scripts/test-javascript.py']
    fingerprint = hashlib.sha256(b''.join((ROOT / name).read_bytes() for name in audited_files)).hexdigest()
    report.write_text(json.dumps({'spidermonkey_revision': REVISION, 'passed': True,
        'asan_ubsan_embedding': True, 'engine_itself_sanitized': False, 'jit_enabled': False,
        'language_assertions': 12, 'script_rendering': True, 'timeout_recovery': True,
        'native_bridge_limits': True, 'context_teardown': True, 'tested_on': 'Linux host, NOT PS4',
        'javascript_executed_on_console': False, 'source_fingerprint': fingerprint}, indent=2) + '\n')
    print('Real SpiderMonkey host embedding tests passed; console execution remains unverified.')

if __name__ == '__main__':
    main()
