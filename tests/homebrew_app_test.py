# SPDX-License-Identifier: MIT
"""Native application lane checks. ELF links are not console execution."""
from pathlib import Path
import json
import os
import runpy
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
APP = runpy.run_path(str(ROOT / 'scripts/build-gecko-app.py'))
IMPORTS = {'malloc', 'calloc', 'realloc', 'free', 'memalign', 'posix_memalign',
           'flockfile', 'ftrylockfile', 'funlockfile', 'clock_gettime', 'clock_getres',
           'pthread_condattr_setclock', 'pthread_condattr_getclock',
           'pthread_getthreadid_np', 'sysconf'}


class HomebrewAppTest(unittest.TestCase):
    def test_engine_selection_rejects_cross_lane_and_native_mesa_before_output(self):
        for sdk in ('openorbis', 'homebrew'):
            for native in (False, True):
                config = {'defines': {'MOZ_ORBIS_HOMEBREW_SDK': native}}
                if native == (sdk == 'homebrew'):
                    APP['require_engine_sdk'](config, sdk)
                else:
                    with self.assertRaises(RuntimeError):
                        APP['require_engine_sdk'](config, sdk)
        for args in (['--sdk', 'homebrew', '--mesa'], ['--sdk', 'homebrew', '--jobs', '0']):
            result = subprocess.run(['python3', str(ROOT / 'scripts/build-gecko-app.py'), *args],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Native SDK Mesa closure is not migrated' if '--mesa' in args else
                          'Select a known SDK and jobs', result.stderr)

    def test_current_sdk_runtime_binding_and_changed_archive_rejection(self):
        inputs = APP['native_runtime_inputs']()
        self.assertEqual(inputs['runtime'], ROOT / '.deps/libcxx-homebrew/lib')
        self.assertEqual(inputs['guard_thread_id']['thread_id_import'], 'pthread_getthreadid_np')
        self.assertEqual(inputs['sdk_identity']['revision'],
                         'ecc8347aa20d7b3423405a5e94d7ab119485160d')
        original = APP['fingerprint']
        def changed(path):
            result = original(path)
            if Path(path) == inputs['runtime'] / 'libc++abi.a':
                result['sha256'] = '0' * 64
            return result
        with patch.dict(APP['native_runtime_inputs'].__globals__, fingerprint=changed):
            with self.assertRaisesRegex(RuntimeError, 'private C\\+\\+ archive binding changed'):
                APP['native_runtime_inputs']()

    def test_native_entrypoint_prepares_font_before_outputs_with_valid_run_signature(self):
        class CheckedFont(Exception):
            pass

        calls = []

        def checked_run(command, *, log=None):
            calls.append(command)
            self.assertEqual(command[-1].name, 'fetch-native-font-header.py')
            self.assertIsNone(log)
            raise CheckedFont()

        main = APP['main']
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            engine = root / 'engine'
            engine.mkdir()
            (engine / 'build-report.json').write_text(json.dumps({'full_engine_linked': True}))
            (engine / 'config.status.json').write_text(json.dumps({
                'defines': {'MOZ_ORBIS_HOMEBREW_SDK': 1}}))
            changes = {'ROOT': root, 'ENGINE': engine, 'run': checked_run,
                       'BUILD': main.__globals__['BUILD']}
            with patch.dict(main.__globals__, changes), patch.dict(os.environ), \
                    patch.object(sys, 'argv', ['build-gecko-app.py', '--sdk', 'homebrew', '--skip-engine-build']):
                with self.assertRaises(CheckedFont):
                    main()
            self.assertEqual(len(calls), 1)
            self.assertFalse((root / 'build').exists())

    def test_native_chrome_compiles_with_verified_single_font_header(self):
        inputs = APP['native_runtime_inputs']()
        flags = APP['native_application_includes'](inputs)
        self.assertEqual(inputs['font_header']['sha256'],
                         '97233cfddd15dc96ea28d73b10599887584c38e3166b4cd3ef62934cb79b20e6')
        self.assertIn(str(ROOT / '.deps/native-font-header'), flags)
        self.assertFalse(any('OpenOrbis' in flag for flag in flags))
        driver = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'chrome.o'
            command = driver['compiler_command'](['--cxx', '-std=c++20',
                '-I' + str(ROOT / 'include'), *flags, '-c',
                str(ROOT / 'src/native_chrome.cpp'), '-o', str(output)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', '--defined-only', '--demangle', str(output)], text=True)
            self.assertIn('orbisfox::NativeChrome::render(', symbols)

    def test_native_boundary_rejects_legacy_interposers_and_missing_imports(self):
        code = {'catchReturnFromMain', 'orbisfox_startup_dispatch', '__wrap_sysconf'}
        result = APP['verify_native_boundaries'](code, code, IMPORTS)
        self.assertFalse(result['native_cpp_shutdown_console_verified'])
        self.assertFalse(result['native_heap_size_instrumentation_available'])
        for symbol in ('__lockfile', '__wrap_free', '__wrap___mmap',
                       'orbisfox_sdk_malloc_state', '__orbisfox_initializers_start'):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                APP['verify_native_boundaries'](code | {symbol}, code | {symbol}, IMPORTS)
        for name in IMPORTS:
            with self.subTest(missing=name), self.assertRaises(ValueError):
                APP['verify_native_boundaries'](code, code, IMPORTS - {name})
            with self.subTest(redefined=name), self.assertRaises(ValueError):
                APP['verify_native_boundaries'](code | {name}, code | {name}, IMPORTS - {name})
        with self.assertRaisesRegex(ValueError, 'code bodies are missing'):
            APP['verify_native_boundaries'](code - {'catchReturnFromMain'}, code, IMPORTS)

    def test_actual_sdk_elf_keeps_native_imports_crt_and_real_return_hook(self):
        driver = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
        service = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))
        service['verify']()
        native_inputs = APP['native_runtime_inputs']()
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            source = temp / 'imports.cpp'
            source.write_text('''#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>
#include <pthread_np.h>
#include <time.h>
#include <unistd.h>
extern "C" void* memalign(size_t, size_t);
namespace orbisfox {void log(const char*,...) {}}
__attribute__((used)) void* native_imports[] = {
''' + ',\n'.join('reinterpret_cast<void*>(&::' + name + ')' for name in sorted(IMPORTS)) + '\n};\n')
            elf = temp / 'native.elf'
            sources = ['src/ps4/startup.cpp', 'src/ps4/homebrew_return.cpp',
                       'src/ps4/native_cpu.cpp', 'src/ps4/services.cpp', 'src/ps4/modules.cpp',
                       'tests/homebrew_startup_fixture.cpp', 'src/surface.cpp',
                       'src/touch_cursor.cpp', 'src/native_ui_loop.cpp', 'src/native_chrome.cpp']
            objects = []
            for index, path in enumerate([*[ROOT / path for path in sources], source]):
                obj = temp / (str(index) + '.o')
                command = driver['compiler_command'](['--cxx', '-std=c++20', '-O0',
                    '-DORBISFOX_FULL_GECKO', '-I' + str(ROOT / 'include'),
                    *APP['native_application_includes'](native_inputs),
                    '-c', str(path), '-o', str(obj)])
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                objects.append(obj)
            response = temp / 'inputs.rsp'
            response.write_text('\n'.join(str(obj) for obj in objects) + '\n')
            sdk = ROOT / '.deps/ps4-homebrew-sdk-v0.2.1/target'
            command = APP['native_link_command'](sdk, ROOT / '.deps/libcxx-homebrew/lib', elf, response)
            self.assertIn('defs', command)
            self.assertNotIn('--allow-shlib-undefined', command)
            self.assertIn('--undefined=_ZN8orbisfox13LatestUiFrame4readERm', command)
            self.assertFalse(any('ps4-gecko.ld' in str(arg) or 'libcxx-orbis' in str(arg)
                                 for arg in command))
            # Retain every fixture anchor; the production command retains GC.
            command += ['--no-gc-sections', '--wrap=sysconf', '--undefined=__wrap_sysconf']
            result = subprocess.run([str(arg) for arg in command], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', str(elf)], text=True).splitlines()
            text, defined, undefined = set(), set(), set()
            for line in symbols:
                parts = line.split()
                if len(parts) >= 2 and parts[-2] == 'U':
                    undefined.add(parts[-1])
                elif len(parts) >= 3:
                    defined.add(parts[-1])
                    if parts[-2] in ('t', 'T'):
                        text.add(parts[-1])
            self.assertIn('_ZN8orbisfox13LatestUiFrame4readERm', text)
            report = APP['verify_native_boundaries'](text, defined, undefined)
            self.assertEqual(set(report['native_system_libc_heap_stdio_clock_imports_verified']), IMPORTS)
            startup = runpy.run_path(str(ROOT / 'scripts/verify-startup.py'))['verify'](elf, sdk='homebrew')
            self.assertFalse(startup['console_startup_verified'])


if __name__ == '__main__':
    unittest.main()
