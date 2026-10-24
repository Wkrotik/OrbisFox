#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Build ABI-isolated LLVM C++ runtimes for the pinned native homebrew SDK.

Exports pristine pinned public LLVM sources from the existing local object store.
Never modifies the shared old-SDK checkout and never fetches missing Git objects.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import runpy
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
REVISION = '2078da43e25a4623cab2d0d60decddf709aaea28'  # llvmorg-21.1.8
DIRECTORIES = ['runtimes', 'libcxx', 'libcxxabi', 'libunwind', 'cmake', 'llvm/cmake',
               'llvm/utils/llvm-lit', 'libc/shared', 'libc/src/__support', 'libc/hdr', 'libc/include']
SOURCE = ROOT / '.deps/llvm-runtimes-homebrew'
BUILD = ROOT / 'build/libcxx-homebrew'
INSTALL = ROOT / '.deps/libcxx-homebrew'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_sources():
    marker = SOURCE / '.orbisfox-source.json'
    identity = {'revision': REVISION, 'directories': DIRECTORIES}
    if marker.is_file():
        if json.loads(marker.read_text()) != identity:
            raise RuntimeError('Homebrew LLVM source identity changed')
        return
    if SOURCE.exists():
        raise RuntimeError('Incomplete homebrew LLVM export; inspect it before retrying')
    old = ROOT / '.deps/llvm-runtimes'
    env = dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0')
    actual = subprocess.check_output(['git', '-C', old, 'rev-parse', 'HEAD'], env=env, text=True).strip()
    if actual != REVISION:
        raise RuntimeError('Pinned local LLVM object store is unavailable')
    SOURCE.mkdir(parents=True)
    # Avoid git archive: it requests unrelated sparse-missing .gitattributes.
    # Validate every copied file against the pinned committed blob, reading the
    # original object for old-SDK-modified files. No shared Git writes/fetches.
    tree = subprocess.check_output(['git', '-C', old, 'ls-tree', '-rz', REVISION,
                                    '--', *DIRECTORIES], env=env)
    for item in tree.split(b'\0'):
        if not item:
            continue
        metadata, raw_name = item.split(b'\t', 1)
        mode, kind, object_id = metadata.decode().split()
        name = PurePosixPath(raw_name.decode())
        if kind != 'blob' or name.is_absolute() or '..' in name.parts:
            raise RuntimeError('Unsafe public LLVM source entry')
        original = old / name
        data = os.readlink(original).encode() if mode == '120000' else original.read_bytes()
        actual_blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual_blob != object_id:
            data = subprocess.check_output(['git', '-C', old, 'cat-file', 'blob', object_id], env=env)
        if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != object_id:
            raise RuntimeError('Pinned LLVM blob mismatch: ' + str(name))
        target = SOURCE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == '120000':
            link = data.decode()
            if not (target.parent / link).resolve().is_relative_to(SOURCE.resolve()):
                raise RuntimeError('Public LLVM link escapes private source tree')
            target.symlink_to(link)
        else:
            target.write_bytes(data)
            target.chmod(0o755 if mode == '100755' else 0o644)
    marker.write_text(json.dumps(identity, indent=2) + '\n')


def patch_guard_thread_id(source=SOURCE):
    path = Path(source) / 'libcxxabi/src/cxa_guard_impl.h'
    text = path.read_text()
    replacements = (
        ('#include <stdlib.h>\n',
         '#include <stdlib.h>\n#if defined(ORBISFOX_HOMEBREW_SDK)\n'
         '#  include <pthread_np.h>\n#endif\n'),
        ('#if defined(__APPLE__) && _LIBCPP_HAS_THREAD_API_PTHREAD\nuint32_t PlatformThreadID() {',
         '#if defined(ORBISFOX_HOMEBREW_SDK) && _LIBCPP_HAS_THREAD_API_PTHREAD\n'
         'uint32_t PlatformThreadID() {\n'
         '  // Native BSD provides genuine IDs even without SYS_gettid. Preserve\n'
         '  // recursive-initialization detection; never invent a shared ID.\n'
         '  const int id = ::pthread_getthreadid_np();\n'
         '  if (id <= 0) ABORT_WITH_MESSAGE("Invalid native C++ guard thread ID");\n'
         '  return static_cast<uint32_t>(id);\n'
         '}\n#elif defined(__APPLE__) && _LIBCPP_HAS_THREAD_API_PTHREAD\nuint32_t PlatformThreadID() {'))
    for old, new in replacements:
        if new not in text:
            if text.count(old) != 1:
                raise RuntimeError('Pinned LLVM native guard thread ID drift')
            text = text.replace(old, new)
    if text.encode() != path.read_bytes():
        path.write_text(text)
    return digest(path)


def verify_guard_provider(archive):
    members = subprocess.check_output(['llvm-ar', 't', str(archive)], text=True).splitlines()
    if members.count('cxa_guard.cpp.o') != 1:
        raise RuntimeError('Native C++ guard archive member missing or ambiguous')
    body = subprocess.check_output(['llvm-ar', 'p', str(archive), 'cxa_guard.cpp.o'])
    with tempfile.TemporaryDirectory(prefix='orbisfox-native-guard-') as tmp:
        path = Path(tmp) / 'guard.o'
        path.write_bytes(body)
        symbols = subprocess.check_output(['llvm-nm', str(path)], text=True)
    entries = {parts[-1]: parts[-2] for line in symbols.splitlines()
               if len(parts := line.split()) >= 2}
    if (entries.get('pthread_getthreadid_np') != 'U' or
            any(entries.get(name) not in ('t', 'T') for name in
                ('__cxa_guard_acquire', '__cxa_guard_release', '__cxa_guard_abort'))):
        raise RuntimeError('Native C++ guards lack real code or genuine thread-ID import')
    return {'member': 'cxa_guard.cpp.o', 'object_sha256': hashlib.sha256(body).hexdigest(),
            'thread_id_import': 'pthread_getthreadid_np', 'code_bodies_verified': True,
            'console_tested': False}


def adapt():
    # FreeBSD 9's umtx header has inline helpers whose atomic declarations are
    # prerequisites; newer FreeBSD headers used by upstream do not need this.
    path = SOURCE / 'libcxx/src/atomic.cpp'
    old = '#  include <sys/types.h>\n#  include <sys/umtx.h>'
    previous = ('#  include <sys/types.h>\n'
                '#  if defined(ORBISFOX_HOMEBREW_SDK)\n'
                '#    include <machine/atomic.h>\n'
                '#  endif\n#  include <sys/umtx.h>')
    new = ('#  include <sys/types.h>\n'
           '#  if defined(ORBISFOX_HOMEBREW_SDK)\n'
           '#    include <machine/atomic.h>\n'
           'extern "C" {\n'
           '#  endif\n#  include <sys/umtx.h>\n'
           '#  if defined(ORBISFOX_HOMEBREW_SDK)\n}\n#  endif')
    text = path.read_text()
    if new not in text:
        text = text.replace(previous, old)
        if text.count(old) != 1:
            raise RuntimeError('Pinned LLVM atomic header prerequisite drift')
        path.write_text(text.replace(old, new))
    patched = {'libcxx/src/atomic.cpp': digest(path)}
    # copy_file_range was introduced in FreeBSD 13, not the native FreeBSD-9
    # surface. Retain upstream's genuine read/write fallback on older systems.
    path = SOURCE / 'libcxx/src/filesystem/operations.cpp'
    old = '#elif defined(__FreeBSD__)\n#  define _LIBCPP_FILESYSTEM_USE_COPY_FILE_RANGE'
    new = '#elif defined(__FreeBSD__) && __FreeBSD__ >= 13\n#  define _LIBCPP_FILESYSTEM_USE_COPY_FILE_RANGE'
    text = path.read_text()
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Pinned LLVM filesystem version guard drift')
        path.write_text(text.replace(old, new))
    patched['libcxx/src/filesystem/operations.cpp'] = digest(path)
    patched['libcxxabi/src/cxa_guard_impl.h'] = patch_guard_thread_id()
    return patched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error('--jobs must be 1..32')
    sdk = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-sdk.py'))
    sdk_report = sdk['verify_sdk']()
    BUILD.mkdir(parents=True, exist_ok=True)
    report = {'started_ns': time.time_ns(), 'sdk': sdk_report,
              'llvm_revision': REVISION, 'target': 'x86_64-scei-ps4',
              'compiler_driver_sha256': digest(ROOT / 'scripts/homebrew-cc.py'),
              'console_tested': False, 'result': None}
    commands = [
        ['cmake', '-G', 'Ninja', '-S', str(SOURCE / 'runtimes'), '-B', str(BUILD),
         '-DCMAKE_SYSTEM_NAME=FreeBSD', '-DCMAKE_SYSTEM_VERSION=9',
         '-DCMAKE_SYSTEM_PROCESSOR=x86_64', '-DCMAKE_TRY_COMPILE_TARGET_TYPE=EXECUTABLE',
         '-DCMAKE_C_COMPILER=' + str(ROOT / 'scripts/homebrew-cc.py'),
         '-DCMAKE_CXX_COMPILER=' + str(ROOT / 'scripts/homebrew-cc.py'),
         '-DCMAKE_CXX_COMPILER_ARG1=--cxx', '-DCMAKE_CXX_FLAGS=-nostdinc++ -nostdlib++',
         '-DCMAKE_AR=/usr/bin/llvm-ar',
         '-DCMAKE_RANLIB=/usr/bin/llvm-ranlib', '-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_POSITION_INDEPENDENT_CODE=ON', '-DCMAKE_INSTALL_PREFIX=' + str(INSTALL),
         '-DLLVM_ENABLE_RUNTIMES=libunwind;libcxxabi;libcxx',
         '-DLIBCXX_CXX_ABI=libcxxabi', '-DLIBCXXABI_USE_LLVM_UNWINDER=ON',
         '-DLIBCXX_HAS_MUSL_LIBC=OFF', '-DLIBCXX_INCLUDE_BENCHMARKS=OFF',
         '-DLLVM_INCLUDE_TESTS=OFF',
         '-DLIBCXX_ENABLE_EXCEPTIONS=ON', '-DLIBCXXABI_ENABLE_EXCEPTIONS=ON',
         # Use real linked ELF DWARF sections; SDK has no dl_iterate_phdr.
         # This does NOT disable threading or replace unwinding with success.
         '-DLIBUNWIND_IS_BAREMETAL=ON', '-DLIBUNWIND_ENABLE_THREADS=ON',
         '-DLIBCXX_ENABLE_THREADS=ON', '-DLIBCXXABI_ENABLE_THREADS=ON',
         '-DLIBCXXABI_HAS_CXA_THREAD_ATEXIT_IMPL=OFF',
         *[f'-D{library}_{option}=OFF' for library in ('LIBCXX', 'LIBCXXABI', 'LIBUNWIND')
           for option in ('ENABLE_SHARED', 'INCLUDE_TESTS', 'USE_COMPILER_RT')]],
        ['cmake', '--build', str(BUILD), '-j', str(args.jobs)],
        ['cmake', '--install', str(BUILD)],
    ]
    report['commands'] = commands
    try:
        export_sources()
        report['patched_sources'] = adapt()
        for command in commands:
            subprocess.run(command, check=True)
        report['guard_thread_id'] = verify_guard_provider(INSTALL / 'lib/libc++abi.a')
        report['libraries'] = {name: digest(INSTALL / 'lib' / name)
                               for name in ('libc++.a', 'libc++abi.a', 'libunwind.a')}
        report['result'] = 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        report['error'] = str(error)
        report['result'] = getattr(error, 'returncode', 1)
        raise
    finally:
        report['finished_ns'] = time.time_ns()
        (BUILD / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
