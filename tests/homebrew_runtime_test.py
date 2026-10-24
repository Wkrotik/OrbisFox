# SPDX-License-Identifier: MIT
"""Native-SDK runtime adapter checks; native link is not console execution."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))


class HomebrewRuntimeTest(unittest.TestCase):
    def test_native_clock_diagnostic_guards_and_error_propagation(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'clock-test'
            command = ['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                       '-fno-omit-frame-pointer', '-pthread', '-I' + str(ROOT / 'include'),
                       str(ROOT / 'tests/homebrew_clock_test.cpp'), '-o', str(exe)]
            subprocess.run(command, capture_output=True, text=True, check=True)
            subprocess.run([str(exe)], capture_output=True, text=True, check=True, timeout=20)

    def test_actual_gecko_clock_startup_gate_uses_native_ids_without_translation(self):
        service = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))
        service['verify']()
        engine = ROOT / 'build/gecko-layout'
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'clock-probe.o'
            flags = ['--cxx', '-std=c++20', '-O1', '-DORBISFOX_FULL_GECKO',
                     '-D__ORBIS__', '-DMOZILLA_INTERNAL_API', '-DIMPL_LIBXUL', '-DMOZ_HAS_MOZGLUE',
                     '-fno-exceptions', '-fno-rtti', '-fno-sized-deallocation', '-fno-aligned-new',
                     '-I' + str(ROOT / 'include'), '-isystem', str(service['DESTINATION'] / 'include'),
                     '-include', str(engine / 'mozilla-config.h'),
                     '-I' + str(engine / 'dist/include'), '-I' + str(engine / 'dist/include/nspr'),
                     '-c', str(ROOT / 'gecko/orbisfox/native/clock_probe.cpp'), '-o', str(output)]
            result = subprocess.run(DRIVER['compiler_command'](flags), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            strings = subprocess.check_output(['strings', str(output)], text=True)
            self.assertIn('native BSD IDs monotonic4/process15/thread14 unchanged', strings)
            self.assertNotIn('monotonic1->firmware4', strings)
            symbols = subprocess.check_output(['llvm-nm', '-u', str(output)], text=True)
            self.assertIn('pthread_condattr_getclock', symbols)
            self.assertIn('pthread_condattr_setclock', symbols)

    def test_actual_sdk_clock_ids_fail_with_legacy_translation_and_pass_native(self):
        if not (ROOT / '.deps/ps4-homebrew-sdk-v0.2.1').is_dir():
            self.skipTest('Fetch the pinned native SDK first')
        source = '''#include "orbisfox/native_clock.h"
#include <errno.h>
static_assert(EAGAIN == 35 && EOVERFLOW == 84 && EPROTO == 92 && EFAULT == 14);
static_assert(CLOCK_MONOTONIC == 4);
static_assert(CLOCK_PROCESS_CPUTIME_ID == 15);
static_assert(orbisfox::firmware_clock_id(CLOCK_MONOTONIC) == 4, "native monotonic must not be remapped");
static_assert(orbisfox::firmware_clock_id(CLOCK_PROCESS_CPUTIME_ID) == 15, "native process CPU must not be remapped");
static_assert(orbisfox::firmware_condition_clock_id(CLOCK_MONOTONIC) == 4);
static_assert(orbisfox::sdk_condition_clock_id(4) == CLOCK_MONOTONIC);
static_assert(orbisfox::firmware_clock_id(999) == -1);
'''
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / 'orbisfox/native_clock.h'
            old.parent.mkdir()
            # Preserve the old algorithm explicitly; do not depend on Git history
            # being present in an exported source archive.
            old.write_text('''#pragma once
#include <time.h>
namespace orbisfox {
constexpr int firmware_clock_id(int id) {
 switch(id) { case 0: return 0; case 1: return 4; case 2: return 2;
 case 3: return 14; case 5: return 10; case 6: return 12; default: return -1; }
}
constexpr int firmware_condition_clock_id(int id) {return id == 0 ? 0 : id == 1 ? 4 : -1;}
constexpr int sdk_condition_clock_id(int id) {return id == 0 ? 0 : id == 4 ? 1 : -1;}
}
''')
            for include, expected in ((Path(tmp), False), (ROOT / 'include', True)):
                command = DRIVER['compiler_command'](['--cxx', '-nostdinc++', '-std=c++20',
                           '-I' + str(include), '-x', 'c++', '-fsyntax-only', '-'])
                result = subprocess.run(command, input=source, capture_output=True, text=True)
                if expected:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('native monotonic must not be remapped', result.stderr)
                    self.assertIn('native process CPU must not be remapped', result.stderr)

    def test_native_sdk_compiled_fcntl_errors_guards_and_unchanged_bsd_records(self):
        if not (ROOT / '.deps/libcxx-homebrew/lib/libc++.a').is_file():
            self.skipTest('Build the native C++ runtime first')
        with tempfile.TemporaryDirectory() as tmp:
            obj, exe = Path(tmp) / 'fcntl.o', Path(tmp) / 'fcntl-test'
            command = DRIVER['compiler_command'](['--cxx', '-std=c++20', '-DORBISFOX_FULL_GECKO',
                       '-Dfcntl=homebrew_test_fcntl', '-D__error=homebrew_test_errno',
                       '-I' + str(ROOT / 'include'), '-c', str(ROOT / 'src/ps4/native_fcntl.cpp'), '-o', str(obj)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            linked = subprocess.run(['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                                     '-I' + str(ROOT / 'include'), str(ROOT / 'tests/homebrew_fcntl_test.cpp'),
                                     str(obj), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(linked.returncode, 0, linked.stderr)
            executed = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
            self.assertEqual(executed.returncode, 0, executed.stderr)

    def test_actual_native_runtime_links_without_libc_or_pthread_overrides(self):
        if not (ROOT / '.deps/libcxx-homebrew/lib/libc++.a').is_file():
            self.skipTest('Build the native C++ runtime first')
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / 'main.cpp'
            main.write_text('''#include "orbisfox/native_clock.h"
#include "orbisfox/native_stat.h"
#include "orbisfox/native_fcntl.h"
namespace orbisfox { void log(const char*, ...) {} }
int main() { timespec output{}; return orbisfox::firmware_clock_gettime(CLOCK_MONOTONIC, &output)
 + !orbisfox::probe_native_filesystem_metadata() + !orbisfox::probe_native_file_locks(); }
''')
            elf = Path(tmp) / 'clock.elf'
            command = DRIVER['compiler_command'](['--cxx', '-std=c++20', '-DORBISFOX_FULL_GECKO',
                       '-I' + str(ROOT / 'include'), str(main),
                       *[str(ROOT / 'src/ps4' / name) for name in
                         ('native_clock.cpp', 'native_stat.cpp', 'native_fcntl.cpp')],
                       '-Wl,--no-gc-sections', '-o', str(elf)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            defined = subprocess.check_output(['llvm-nm', '--defined-only', '--demangle', str(elf)], text=True)
            self.assertIn('orbisfox::firmware_clock_gettime(', defined)
            for name in ('clock_gettime', 'clock_getres', 'stat', 'lstat', 'fstat', 'fcntl',
                         'pthread_condattr_setclock', 'pthread_condattr_getclock'):
                self.assertFalse(any(line.endswith(' ' + name) for line in defined.splitlines()), defined)
            undefined = subprocess.check_output(['llvm-nm', '--undefined-only', str(elf)], text=True)
            for name in ('clock_gettime', 'stat', 'lstat', 'fstat', 'fcntl'):
                self.assertIn(' ' + name + '\n', undefined)
            self.assertNotIn(' sceKernelDlsym\n', undefined)


if __name__ == '__main__':
    unittest.main()
