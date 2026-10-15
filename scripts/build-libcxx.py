#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Cross-build a separate libc++/ABI/unwinder for the experimental Gecko lane."""
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/llvm-runtimes'
REVISION = '2078da43e25a4623cab2d0d60decddf709aaea28'  # llvmorg-21.1.8
DIRECTORIES = ['runtimes', 'libcxx', 'libcxxabi', 'libunwind', 'cmake', 'llvm/cmake',
               'llvm/utils/llvm-lit', 'libc/shared', 'libc/src/__support', 'libc/hdr', 'libc/include']


def git(*args):
    subprocess.run(['git', '-C', str(SOURCE), *args], check=True)


def adapt():
    # Preserve stock FreeBSD behavior; the SDK's libc is a hybrid with musl
    # POSIX interfaces, not FreeBSD libc. Use upstream portable fallbacks.
    patches = {
        'libcxxabi/src/cxa_guard_impl.h': [
            ('#include <stdlib.h>\n', '#include <stdlib.h>\n#if defined(__ORBIS__)\nextern "C" int32_t scePthreadGetthreadid(void);\n#endif\n'),
            ('#if defined(__APPLE__) && _LIBCPP_HAS_THREAD_API_PTHREAD\nuint32_t PlatformThreadID() {',
             '#if defined(__ORBIS__) && _LIBCPP_HAS_THREAD_API_PTHREAD\nuint32_t PlatformThreadID() {\n  // SDK syscall(SYS_gettid) is an ENOSYS stub shared by every thread.\n  // Keep genuine guard ownership/recursion checks with the native thread ID.\n  return static_cast<uint32_t>(scePthreadGetthreadid());\n}\n#elif defined(__APPLE__) && _LIBCPP_HAS_THREAD_API_PTHREAD\nuint32_t PlatformThreadID() {')],
        'libcxx/include/__locale_dir/locale_base_api.h': [
            ('#  elif defined(__FreeBSD__)\n', '#  elif defined(__FreeBSD__) && !_LIBCPP_HAS_MUSL_LIBC\n')],
        'libcxx/include/__configuration/abi.h': [
            ('#  if defined(__FreeBSD__)\n#    define _LIBCPP_DEPRECATED_ABI_DISABLE_PAIR_TRIVIAL_COPY_CTOR',
             '#  if defined(__FreeBSD__) && !defined(__ORBIS__)\n#    define _LIBCPP_DEPRECATED_ABI_DISABLE_PAIR_TRIVIAL_COPY_CTOR')],
        'libcxx/include/__config': [
            ('#  if defined(__APPLE__) || defined(__FreeBSD__) || defined(__NetBSD__) || defined(__OpenBSD__) ||                     \\\n      defined(__DragonFly__)\n#    define _LIBCPP_USING_ARC4_RANDOM',
             '#  if defined(__ORBIS__)\n#    define _LIBCPP_USING_DEV_RANDOM\n#  elif defined(__APPLE__) || defined(__FreeBSD__) || defined(__NetBSD__) || defined(__OpenBSD__) ||                     \\\n      defined(__DragonFly__)\n#    define _LIBCPP_USING_ARC4_RANDOM')],
        'libcxx/src/atomic.cpp': [
            ('#elif defined(__FreeBSD__)\n', '#elif defined(__FreeBSD__) && !defined(__ORBIS__)\n'),
            ('#elif defined(__FreeBSD__) && __SIZEOF_LONG__ == 8',
             '#elif defined(__FreeBSD__) && !defined(__ORBIS__) && __SIZEOF_LONG__ == 8')],
        'libcxx/src/filesystem/operations.cpp': [
            ('#elif defined(__FreeBSD__)\n', '#elif defined(__FreeBSD__) && !defined(__ORBIS__)\n'),
            ('#if __has_include(<sys/sendfile.h>)', '#if __has_include(<sys/sendfile.h>) && !defined(__ORBIS__)')],
    }
    for relative, edits in patches.items():
        file = SOURCE / relative
        text = file.read_text()
        for old, new in edits:
            if new in text:
                continue
            if text.count(old) != 1:
                raise RuntimeError(f'Unexpected LLVM source: {relative}')
            text = text.replace(old, new)
        if file.read_text() != text:
            file.write_text(text)


def main():
    if not (SOURCE / '.git').exists():
        SOURCE.mkdir(parents=True, exist_ok=True)
        git('init', '-q')
        git('remote', 'add', 'origin', 'https://github.com/llvm/llvm-project.git')
        git('-c', 'protocol.version=2', 'fetch', '--depth=1', '--filter=blob:none', 'origin', REVISION)
        git('sparse-checkout', 'init', '--cone')
        git('sparse-checkout', 'set', *DIRECTORIES)
        git('checkout', '--detach', REVISION)
    actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise RuntimeError('LLVM source revision mismatch')
    git('sparse-checkout', 'set', *DIRECTORIES)
    adapt()
    subprocess.run([sys.executable, str(ROOT / 'scripts/sdk-overlay.py')], check=True)
    build = ROOT / 'build/libcxx-orbis'
    configure = ['cmake', '-G', 'Ninja', '-S', str(SOURCE / 'runtimes'), '-B', str(build),
                 '-DCMAKE_SYSTEM_NAME=FreeBSD', '-DCMAKE_SYSTEM_PROCESSOR=x86_64',
                 f'-DCMAKE_C_COMPILER={ROOT / "scripts/orbis-cc.py"}',
                 f'-DCMAKE_CXX_COMPILER={ROOT / "scripts/orbis-cc.py"}', '-DCMAKE_CXX_COMPILER_ARG1=--cxx',
                 '-DCMAKE_AR=/usr/bin/llvm-ar', '-DCMAKE_RANLIB=/usr/bin/llvm-ranlib',
                 '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_POSITION_INDEPENDENT_CODE=ON',
                 '-DCMAKE_C_FLAGS=-DORBISFOX_PTHREAD_ATTR_ABI=2',
                 '-DCMAKE_CXX_FLAGS=-DORBISFOX_PTHREAD_ATTR_ABI=2',
                 f'-DCMAKE_INSTALL_PREFIX={ROOT / ".deps/libcxx-orbis"}',
                 '-DLLVM_ENABLE_RUNTIMES=libunwind;libcxxabi;libcxx',
                 '-DLIBCXX_CXX_ABI=libcxxabi', '-DLIBCXXABI_USE_LLVM_UNWINDER=ON',
                 '-DLIBCXX_HAS_MUSL_LIBC=ON', '-DLIBCXX_ENABLE_BENCHMARKS=OFF',
                 '-DLIBCXX_ENABLE_EXCEPTIONS=OFF', '-DLIBCXXABI_ENABLE_EXCEPTIONS=OFF']
    for library in ('LIBCXX', 'LIBCXXABI', 'LIBUNWIND'):
        configure += [f'-D{library}_ENABLE_SHARED=OFF', f'-D{library}_ENABLE_TESTS=OFF',
                      f'-D{library}_USE_COMPILER_RT=OFF']
    subprocess.run(configure, check=True)
    subprocess.run(['cmake', '--build', str(build), '-j', os.environ.get('ORBISFOX_JOBS', '6')], check=True)
    subprocess.run(['cmake', '--install', str(build)], check=True)
    print('Private libc++ 21 runtime built; application uses private libc++; corrected pthread attribute ABI; hardware testing pending')


if __name__ == '__main__':
    main()
