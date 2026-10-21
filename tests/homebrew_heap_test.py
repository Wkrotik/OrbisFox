# SPDX-License-Identifier: MIT
"""System libc owns native allocation; retain the real behavioral startup gate."""
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
SERVICE = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))


class HomebrewHeapTest(unittest.TestCase):
    def flags(self):
        SERVICE['verify']()
        return ['-std=c++20', '-O1', '-fno-builtin', '-DORBISFOX_FULL_GECKO',
                '-DORBISFOX_HOMEBREW_SDK=1', '-I' + str(ROOT / 'include'),
                '-isystem', str(SERVICE['DESTINATION'] / 'include')]

    def test_sdk_probe_no_gc_link_has_real_heap_imports_and_no_legacy_wrappers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            objects = []
            for name in ('src/ps4/native_allocator.cpp', 'gecko/orbisfox/native/allocator_probe.cpp'):
                output = root / (Path(name).stem + '.o')
                result = subprocess.run(DRIVER['compiler_command'](['--cxx', *self.flags(),
                    '-c', str(ROOT / name), '-o', str(output)]), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                objects.append(output)
            all_symbols = subprocess.check_output(['llvm-nm', *map(str, objects)], text=True)
            for forbidden in ('__wrap_', '__real_', '__libc', 'native_allocator_entry_count',
                              'sdk_direct_heap', 'configure_native_allocator_',
                              'initialize_native_allocator_lock', 'orbisfox_sdk_malloc_state'):
                self.assertNotIn(forbidden, all_symbols)
            imports = {line.split()[-1] for line in all_symbols.splitlines() if ' U ' in line}
            self.assertTrue({'malloc', 'calloc', 'realloc', 'free', 'posix_memalign',
                             'pthread_create', 'pthread_join'} <= imports, all_symbols)
            executable = root / 'native.elf'
            result = subprocess.run(DRIVER['compiler_command'](['--cxx', *self.flags(),
                str(ROOT / 'tests/homebrew_heap_fixture.cpp'), *map(str, objects),
                '-Wl,--no-gc-sections', '-o', str(executable)]), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', '--defined-only', str(executable)], text=True)
            for name in ('malloc', 'calloc', 'realloc', 'free', 'memalign', 'posix_memalign'):
                self.assertIsNone(re.search(r'\b[tT]\s+' + name + r'$', symbols, re.MULTILINE), symbols)

    def test_configured_native_application_compiles_without_legacy_heap_dependencies(self):
        engine = ROOT / 'build/gecko-layout'
        # Requires the same actual generated headers as the configured NSPR
        # suite; a stale/missing header must fail, not silently skip the gate.
        flags = self.flags() + ['-D__ORBIS__', '-DORBISFOX_NATIVE_RUN_LOGS',
            '-DMOZILLA_INTERNAL_API', '-DIMPL_LIBXUL', '-DMOZ_HAS_MOZGLUE',
            '-fno-exceptions', '-fno-rtti', '-fno-sized-deallocation', '-fno-aligned-new',
            '-include', str(engine / 'mozilla-config.h')]
        flags += ['-I' + str(engine / name) for name in ('dist/include', 'dist/include/nspr', 'dist/include/nss')]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'main.o'
            result = subprocess.run(DRIVER['compiler_command'](['--cxx', *flags,
                '-c', str(ROOT / 'gecko/orbisfox/native/main.cpp'), '-o', str(output)]),
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', '-u', str(output)], text=True)
            for forbidden in ('native_allocator_audited_arena_count', 'sdk_direct_heap',
                              'configure_native_allocator_', 'checkpoint_native_allocator_'):
                self.assertNotIn(forbidden, symbols)
            self.assertIn('probe_native_allocator', symbols)
            self.assertRegex(symbols, r'\bU environ\b')

    def test_native_sdk_rejects_legacy_allocator_modes(self):
        for mode in ('ORBISFOX_SDK_BIN_AUDIT', 'ORBISFOX_NATIVE_DIRECT_HEAP', 'ORBISFOX_SDK_REALLOC_COMPAT'):
            result = subprocess.run(DRIVER['compiler_command'](['--cxx', *self.flags(), '-D' + mode,
                '-fsyntax-only', str(ROOT / 'src/ps4/native_allocator.cpp')]), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Native SDK allocator must not use legacy', result.stderr)

    def test_host_pattern_realloc_zero_alignment_handoff_and_partial_worker_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'test'
            result = subprocess.run(['clang++', *self.flags(), '-DORBISFOX_HEAP_PROBE_HOST',
                '-fsanitize=address,undefined', '-g', '-pthread',
                str(ROOT / 'gecko/orbisfox/native/allocator_probe.cpp'),
                str(ROOT / 'tests/homebrew_heap_fixture.cpp'), '-Wl,--wrap=pthread_create,--wrap=calloc',
                '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for arguments in (['0'], ['1'], ['2'], ['5'], ['9'], ['0', 'corrupt-zero']):
                result = subprocess.run([str(exe), *arguments], capture_output=True, text=True, timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if arguments == ['0']:
                    self.assertIn('8-thread pattern-realloc-calloc-alignment-handoff: PASS', result.stdout)
                if len(arguments) > 1:
                    self.assertIn('allocator reuse canaries: FAIL', result.stdout)
                    self.assertNotIn('error-mask=0x0 ', result.stdout)
                self.assertNotIn('SDK-libc+12', result.stdout)
                self.assertNotIn('protected-entries=', result.stdout)


if __name__ == '__main__':
    unittest.main()
