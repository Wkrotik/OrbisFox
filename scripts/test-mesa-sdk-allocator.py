#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Actual pinned Mesa ralloc and installed SDK objects; Linux shims, not PS4 proof.

Explicit diagnostic test (not part of ordinary source-only tests). Prepares the
existing genuine-SDK matrix first; does not modify any console or SDK input.
"""
from pathlib import Path
import hashlib
import itertools
import json
import os
import resource
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/mesa-sdk-allocator-host'
SDK_OUT = ROOT / 'build/sdk-allocator-host'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / 'test-report.json'
    report_path.unlink(missing_ok=True)
    producer = runpy.run_path(str(ROOT / 'scripts/build-orbis-mesa.py'))
    mesa = ROOT / '.deps/mesa-ps4'
    pin = producer['PINS']['mesa-ps4']
    revision = subprocess.check_output(['git', '-C', mesa, 'rev-parse', 'HEAD'], text=True).strip()
    if revision != pin:
        raise RuntimeError('Mesa SDK reproduction requires the pinned Mesa checkout')
    ralloc = mesa / 'src/util/ralloc.c'
    upstream = subprocess.check_output(['git', '-C', mesa, 'show', pin + ':src/util/ralloc.c'])
    if ralloc.read_bytes() != upstream:
        raise RuntimeError('Mesa ralloc source changed; refusing to mislabel a modified reproduction')
    subprocess.run(['/usr/bin/python3', ROOT / 'scripts/test-sdk-allocator.py'], check=True)
    sdk_test = runpy.run_path(str(ROOT / 'scripts/test-sdk-allocator.py'))
    sdk_report = json.loads((SDK_OUT / 'test-report.json').read_text())
    objects = [SDK_OUT / (member + '.renamed.o') for member in sdk_test['MEMBERS']]
    for member, expected in sdk_report['object_hashes'].items():
        original = subprocess.check_output(['llvm-ar', 'p', sdk_test['ARCHIVE'], member])
        if hashlib.sha256(original).hexdigest() != expected:
            raise RuntimeError('Installed SDK objects changed during reproduction preparation')
    sdk_names = ('malloc', 'free', 'calloc', 'realloc', 'aligned_alloc', 'posix_memalign',
                 'memalign', '__memalign', 'valloc', 'malloc_usable_size')
    c_command = ['clang', '-std=c11', '-DNDEBUG', '-D_GNU_SOURCE', '-DHAVE_ENDIAN_H',
                 '-DHAVE_STRUCT_TIMESPEC', '-DHAVE_PTHREAD', '-O3', '-g',
                 '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                 '-ffunction-sections', '-fdata-sections', '-I' + str(mesa / 'src'),
                 '-I' + str(mesa / 'include')]
    for name in ('malloc', 'calloc', 'realloc', 'free'):
        c_command.append('-D' + name + '=__wrap_' + name)
    for name in ('memcpy', 'memset', 'memmove'):
        c_command.append('-D' + name + '=sdk_' + name)
    c_command += ['-c', str(ralloc), '-o', str(OUT / 'ralloc.o')]
    cpp_command = ['clang++', '-std=c++20', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                   '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                   '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
                   '-DORBISFOX_FULL_GECKO', '-DORBISFOX_SDK_BIN_AUDIT',
                   '-DORBISFOX_INSTALLED_SDK_OBJECTS', '-DORBISFOX_NATIVE_DIRECT_HEAP',
                   '-DORBISFOX_NATIVE_RUN_LOGS',
                   '-DSDK_TEST_NESTED_LINK', '-Dgetpagesize=sdk_os_getpagesize',
                   '-I' + str(ROOT / 'include'), '-I' + str(mesa / 'src'),
                   str(ROOT / 'tests/mesa_sdk_allocator_test.cpp'),
                   str(ROOT / 'src/ps4/native_allocator.cpp'),
                   str(ROOT / 'src/ps4/sdk_heap_memory.cpp'),
                   str(SDK_OUT / 'sdk-os-shims.cpp'), str(OUT / 'ralloc.o'),
                   *map(str, objects), *['-Wl,--wrap=sdk_' + name for name in sdk_names],
                   *['-Wl,--wrap=sdk_os_' + name for name in ('expand_heap', 'madvise', 'munmap', 'mmap')],
                   '-pthread', '-o', str(OUT / 'replay')]
    (OUT / 'commands.json').write_text(json.dumps([c_command, cpp_command], indent=2) + '\n')
    with (OUT / 'compile.log').open('w') as log:
        for command in (c_command, cpp_command):
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    cases = []
    for locks in (False, True):
        for direct, capture in itertools.product((False, True), repeat=2):
            env = os.environ.copy()
            for name in ('SDK_TEST_HEAP_GUARDS', 'SDK_TEST_ONLY_MAPPED_SHRINK',
                         'SDK_TEST_FORCE_EXPAND_FAILURE', 'SDK_TEST_RECLAIM_UNSUPPORTED',
                         'SDK_TEST_BIN_LOCKS', 'SDK_TEST_DIRECT_BACKING', 'SDK_TEST_RUNTIME_LOGGING'):
                env.pop(name, None)
            env['SDK_TEST_MREMAP_ENOSYS'] = '1'
            if locks:
                env['SDK_TEST_BIN_LOCKS'] = '1'
            if direct:
                env['SDK_TEST_DIRECT_BACKING'] = '1'
            if capture:
                env['SDK_TEST_RUNTIME_LOGGING'] = '1'
            log_path = OUT / f'locks-{int(locks)}-direct-{int(direct)}-capture-{int(capture)}.log'
            def no_core():
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            with log_path.open('w') as log:
                subprocess.run([str(OUT / 'replay')], env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=180, preexec_fn=no_core)
            cases.append({'modeled_sdk_lock_flag': locks, 'modeled_direct_backing': direct,
                          'runtime_diagnostics': capture, 'mremap_ENOSYS': True, 'passed': True, 'log': str(log_path)})
    report = {'passed': True, 'mesa_revision': pin, 'ralloc_sha256': digest(ralloc),
              'sdk_object_sha256': sdk_report['object_hashes'],
              'harness_sha256': digest(ROOT / 'tests/mesa_sdk_allocator_test.cpp'),
              'native_allocator_sha256': digest(ROOT / 'src/ps4/native_allocator.cpp'),
              'cases': cases, 'workers': 8, 'root_cycles_per_worker': 128,
              'actual_sdk_memory_primitives': True, 'sdk_objects_sanitized': False,
              'mesa_and_wrapper_sanitized': True, 'broader_endpoint_bin_audit_follows_runtime_diagnostics': True,
              'interior_free_bin_nodes_audited': False, 'firmware_tested': False,
              'limitations': 'Linux OS and direct-memory doubles; no GPU, PS4 printf/thread ABI, browser rendering or observed console causal chain'}
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print('Mesa ralloc / genuine SDK host replay: eight 8-worker cases PASS; not console proof')


if __name__ == '__main__':
    main()
