# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
CONFIGURE = runpy.run_path(str(ROOT / 'scripts/configure-gecko-layout.py'))


class HomebrewToolchainTest(unittest.TestCase):
    def test_native_target_is_not_overridden_by_configure(self):
        for target in sorted(DRIVER['LEGACY_TARGETS'] | {DRIVER['NATIVE_TARGET']}):
            for flags in (['--target=' + target], ['-target', target]):
                args = DRIVER['compiler_command']([*flags, '-c', 'test.c'])
                self.assertNotIn(target, ' '.join(args))
                self.assertEqual(Path(args[0]).name, 'orbis-clang')
                self.assertIn('-DORBISFOX_HOMEBREW_SDK=1', args)

    def test_rejects_other_targets_sysroots_and_old_runtime(self):
        for flags in (['--target=x86_64-linux-gnu'], ['--target'],
                      ['--sysroot=/tmp/old'], ['-isysroot', '/tmp/old'],
                      ['-I.deps/sdk-overlay'], ['-L.deps/libcxx-orbis/lib'],
                      ['-I' + str(ROOT / '.deps/OpenOrbis/PS4Toolchain/include')]):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                DRIVER['compiler_command'](flags)

    def test_cpp_cannot_silently_use_host_headers_or_old_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, 'headers missing'):
                DRIVER['compiler_command'](['--cxx', '-c', 'test.cpp'], root=root)
            headers = root / '.deps/libcxx-homebrew/include/c++/v1'
            headers.mkdir(parents=True)
            args = DRIVER['compiler_command'](['--cxx', '-c', 'test.cpp'], root=root)
            self.assertIn('-nostdinc++', args)
            self.assertIn('-nostdlib++', args)
            self.assertIn(str(headers), args)
            with self.assertRaisesRegex(RuntimeError, 'archives missing'):
                DRIVER['compiler_command'](['--cxx', 'test.o', '-o', 'test'], root=root)
            libraries = root / '.deps/libcxx-homebrew/lib'
            libraries.mkdir()
            for name in ('libc++.a', 'libc++abi.a', 'libunwind.a'):
                (libraries / name).touch()
            args = DRIVER['compiler_command'](['--cxx', 'test.o', '-o', 'test'], root=root)
            self.assertIn('-L' + str(libraries), args)
            self.assertEqual(args[-3:], ['-lc++', '-lc++abi', '-lunwind'])

    def test_raw_bindgen_flags_use_native_abi_and_cpp_before_c_headers(self):
        if not (ROOT / '.deps/libcxx-homebrew/include/c++/v1').is_dir():
            self.skipTest('Native C++ runtime not built')
        flags = CONFIGURE['native_bindgen_flags']()
        cpp = str(ROOT / '.deps/libcxx-homebrew/include/c++/v1')
        c = str(ROOT / '.deps/ps4-homebrew-sdk-v0.2.1/target/include')
        self.assertLess(flags.index(cpp), flags.index(c))
        self.assertEqual(flags[flags.index(c) - 1], '-idirafter')
        text = '''#include <cmath>
#include <cctype>
#include <cwctype>
#include <cwchar>
#include <cstring>
#include <memory_resource>
#include <emmintrin.h>
#include <pthread.h>
#include <time.h>
static_assert(sizeof(wchar_t)==2 && sizeof(pthread_once_t)==16);
static_assert(CLOCK_MONOTONIC==4 && CLOCK_PROCESS_CPUTIME_ID==15);
std::mbstate_t state;
auto operation(double x) {return std::sqrt(x);}
'''
        old = [flag for flag in flags if not flag.startswith('--sysroot=')]
        cpp_index, c_index = old.index(cpp), old.index(c)
        old[cpp_index], old[c_index] = c, cpp
        for options, expected in ((old, False), (flags, True)):
            # Raw clang, not the SDK wrapper: this is libclang's header route.
            result = subprocess.run(['clang++', *options, '-std=c++20', '-x', 'c++',
                                     '-fsyntax-only', '-'], input=text, text=True, capture_output=True)
            if expected:
                self.assertEqual(result.returncode, 0, result.stderr)
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('header search paths', result.stderr)

    def test_bootstrap_and_syntax_checks_do_not_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            for flag in ('-c', '-E', '-S', '-fsyntax-only'):
                args = DRIVER['compiler_command'](['--cxx', '-nostdinc++', flag, 'test.cpp'], root=Path(tmp))
                self.assertNotIn('-lc++', args)

    def test_actual_native_headers_and_c_cpp_agree(self):
        sdk = ROOT / '.deps/ps4-homebrew-sdk-v0.2.1'
        if not sdk.is_dir():
            self.skipTest('Pinned new SDK not fetched')
        for cxx in (False, True):
            text = '''#include <stddef.h>
#include <sys/types.h>
#include <pthread.h>
#include <time.h>
#include <sys/stat.h>
#ifdef __cplusplus
#define CHECK static_assert
#else
#define CHECK _Static_assert
#endif
CHECK(sizeof(wchar_t) == 2, "native wchar ABI");
CHECK(sizeof(pthread_t) == 8, "native thread ABI");
CHECK(sizeof(pthread_mutex_t) == 8, "native mutex ABI");
CHECK(sizeof(pthread_cond_t) == 8, "native condition ABI");
CHECK(sizeof(pthread_once_t) == 16, "native once ABI");
CHECK(sizeof(pthread_mutexattr_t) == 8, "native attribute ABI");
CHECK(CLOCK_MONOTONIC == 4, "native clock ABI");
CHECK(CLOCK_THREAD_CPUTIME_ID == 14, "native CPU clock ABI");
CHECK(CLOCK_PROCESS_CPUTIME_ID == 15, "native process clock ABI");
'''
            command = DRIVER['compiler_command']([
                *(['--cxx', '-nostdinc++'] if cxx else []),
                '--target=x86_64-orbis-freebsd12.0', '-x', 'c++' if cxx else 'c',
                '-std=c++17' if cxx else '-std=c11', '-fsyntax-only', '-'])
            result = subprocess.run(command, input=text, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_configure_platform_name_preserves_real_native_compiler_abi(self):
        if not (ROOT / '.deps/ps4-homebrew-sdk-v0.2.1').is_dir():
            self.skipTest('Pinned new SDK not fetched')
        command = DRIVER['compiler_command'](['--target=x86_64-orbis-freebsd9.0', '-x', 'c', '-dM', '-E', '-'])
        self.assertNotIn('--target=x86_64-orbis-freebsd9.0', command)
        result = subprocess.run(command, input='', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('#define __FreeBSD__ 9', result.stdout)
        self.assertIn('#define __WCHAR_WIDTH__ 16', result.stdout)

    def test_native_cpp_link_has_real_runtime_and_unwind_sections(self):
        if not (ROOT / '.deps/libcxx-homebrew/lib/libc++.a').is_file():
            self.skipTest('Native C++ runtime not built; run build-homebrew-libcxx.py')
        with tempfile.TemporaryDirectory() as tmp:
            elf = Path(tmp) / 'link.elf'
            result = subprocess.run(DRIVER['compiler_command']([
                '--cxx', '-std=c++20', str(ROOT / 'tests/homebrew_cpp_link.cpp'), '-o', str(elf)]),
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', '--defined-only', str(elf)], text=True)
            addresses = {fields[2]: int(fields[0], 16) for line in symbols.splitlines()
                         if len(fields := line.split()) == 3}
            self.assertGreater(addresses['__eh_frame_end'], addresses['__eh_frame_start'])
            self.assertIn('_Unwind_RaiseException', addresses)
            self.assertIn('__cxa_throw', addresses)
            self.assertNotIn('dl_iterate_phdr', addresses)
            undefined = subprocess.check_output(['llvm-nm', '--undefined-only', str(elf)], text=True)
            self.assertFalse(any(line.strip().startswith('U _Z') for line in undefined.splitlines()), undefined)

    def test_explicit_no_cpp_runtime_is_respected_for_bootstrap_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = DRIVER['compiler_command'](['--cxx', '-nostdinc++', '-nostdlib++', 'test.o'], root=Path(tmp))
            self.assertNotIn('-lc++', args)
            args = DRIVER['compiler_command'](['-nostdlib', 'test.o'], root=Path(tmp))
            self.assertIn('-nodefaultlibs', args)

    def test_cc_rs_facade_alias_still_compiles_the_native_sdk_abi(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported homebrew compiler target'):
            DRIVER['compiler_command'](['--target=x86_64-scei-freebsd', '-E', '-'])
        env = dict(os.environ, ORBISFOX_SDK='homebrew')
        result = subprocess.run([
            sys.executable, str(ROOT / 'scripts/orbis-cc.py'),
            '--target=x86_64-scei-freebsd', '-x', 'c', '-fsyntax-only', '-'],
            env=env, input='''#include <stddef.h>
#include <pthread.h>
#include <time.h>
_Static_assert(sizeof(wchar_t)==2, "native wchar");
_Static_assert(sizeof(pthread_once_t)==16, "native once");
_Static_assert(CLOCK_MONOTONIC==4 && CLOCK_PROCESS_CPUTIME_ID==15, "native clocks");
_Static_assert(__FreeBSD__==9, "native BSD");
''', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_router_rejects_unknown_selection_before_compile(self):
        result = subprocess.run([str(ROOT / 'scripts/orbis-cc.py'), '--version'],
                                env=dict(os.environ, ORBISFOX_SDK='typo'), capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unknown ORBISFOX_SDK', result.stderr)


if __name__ == '__main__':
    unittest.main()
