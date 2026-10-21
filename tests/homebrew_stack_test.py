# SPDX-License-Identifier: MIT
"""Native thread stack queries: actual SDK API, not a Linux-shaped shim."""
import os
from pathlib import Path
import resource
import runpy
import shlex
import signal
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
RELATIVE = 'js/src/util/NativeStack.cpp'


class HomebrewStackTest(unittest.TestCase):
    def original(self):
        text = subprocess.check_output(['git', '-C', str(SOURCE), 'show', PATCH['REVISION'] + ':' + RELATIVE], text=True)
        # Reproduce the existing legacy producer prerequisite only.
        return text.replace('#  if defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__DragonFly__)',
                            '#  if (defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__DragonFly__)) && !defined(__ORBIS__)')

    def fixture(self, root):
        path = root / RELATIVE
        path.parent.mkdir(parents=True)
        path.write_text(self.original())
        return path

    def test_unknown_owned_edits_fail_before_either_insertion_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            original = path.read_text()
            path.write_text(original.replace('// Since we rearrange the layout', '// Unknown anchor edit'))
            before = path.read_bytes(), path.stat().st_mtime_ns
            with self.assertRaisesRegex(RuntimeError, 'stack query drift'):
                PATCH['patch_native_js_stack'](root)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            path.write_text(original)
            PATCH['patch_native_js_stack'](root)
            path.write_text(path.read_text().replace('native pthread_attr_get_np failed', 'unknown owned edit'))
            before = path.read_bytes(), path.stat().st_mtime_ns
            with self.assertRaisesRegex(RuntimeError, 'stack query drift'):
                PATCH['patch_native_js_stack'](root)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_real_sdk_whole_unit_red_green_and_idempotency(self):
        backend = ROOT / 'build/gecko-layout/js/src/util/backend.mk'
        if not backend.is_file():
            self.skipTest('Requires configured native SDK Gecko backend and exported headers')
        flags = shlex.split(next(line.split(' += ', 1)[1] for line in backend.read_text().splitlines()
                                 if line.startswith('COMPUTED_CXXFLAGS += ')))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_js_stack'](root)
                    before = path.read_bytes(), path.stat().st_mtime_ns
                    PATCH['patch_native_js_stack'](root)
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
                output = root / 'stack.o'
                result = subprocess.run(DRIVER['compiler_command']([
                    '--cxx', '-std=gnu++20', *flags, '-c', str(path), '-o', str(output)]),
                    capture_output=True, text=True)
                if not patched:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("undeclared identifier 'pthread_getattr_np'", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    symbols = subprocess.check_output(['llvm-nm', '-u', str(output)], text=True)
                    for api in ('pthread_attr_init', 'pthread_attr_get_np', 'pthread_attr_getstack', 'pthread_attr_destroy'):
                        self.assertIn(' U ' + api + '\n', symbols)
                    self.assertNotIn('pthread_getattr_np', symbols)

    def test_sdk_compiled_checked_query_host_failures_and_stack_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            PATCH['patch_native_js_stack'](root)
            text = path.read_text()
            start = text.index('#elif defined(ORBISFOX_HOMEBREW_SDK)\n\nvoid*')
            end = text.index('#elif defined(__wasi__)', start)
            # Use the exact production native branch, except Gecko's crash
            # reporting graph. Failed release assertions still emit a trap.
            fragment = text[start:end].split('\n', 1)[1]
            unit = root / 'query.cpp'
            unit.write_text('''#include <stdint.h>
#include <pthread.h>
#include <pthread_np.h>
#define MOZ_RELEASE_ASSERT(value,...) do {if(!(value)) __builtin_trap();} while(0)
#define JS_STACK_GROWTH_DIRECTION -1
namespace js {void* GetNativeStackBaseImpl();}
''' + fragment)
            obj = root / 'query.o'
            result = subprocess.run(DRIVER['compiler_command']([
                '--cxx', '-std=c++20', '-O1', '-c', str(unit), '-o', str(obj)]), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Rename only this object's API references, never interpose on the
            # host/ASan pthread runtime or change the SDK's actual ABI/layout.
            names = ('pthread_attr_init', 'pthread_attr_get_np', 'pthread_attr_getstack', 'pthread_attr_destroy', 'pthread_self')
            rename = [arg for name in names for arg in ('--redefine-sym', name + '=fixture_' + name.removeprefix('pthread_'))]
            subprocess.run(['llvm-objcopy', *rename, str(obj)], check=True)
            exe = root / 'host'
            result = subprocess.run(['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                                     str(ROOT / 'tests/homebrew_stack_fixture.cpp'), str(obj), '-o', str(exe)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            env = dict(os.environ)
            env['ASAN_OPTIONS'] = env.get('ASAN_OPTIONS', '') + ':handle_sigill=0'
            def no_core():
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            for mode in range(8):
                result = subprocess.run([str(exe), str(mode)], capture_output=True, text=True,
                                        timeout=10, env=env, preexec_fn=no_core)
                self.assertEqual(result.returncode, 0 if mode==0 else -signal.SIGILL, result.stderr)
                if mode==1:
                    self.assertNotIn('DESTROY', result.stderr)
                else:
                    self.assertIn('DESTROY query=1 stack=' + ('0' if mode==2 else '1'), result.stderr)


if __name__ == '__main__':
    unittest.main()
