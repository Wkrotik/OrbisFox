# SPDX-License-Identifier: MIT
"""Genuine native ID for libc++abi guards; no allocator/guard ABI change."""
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
BUILDER = runpy.run_path(str(ROOT / 'scripts/build-homebrew-libcxx.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
RELATIVE = 'libcxxabi/src/cxa_guard_impl.h'
SOURCE = ROOT / '.deps/llvm-runtimes-homebrew'


class HomebrewGuardTest(unittest.TestCase):
    def fixture(self, root):
        original = subprocess.check_output([
            'git', '-C', str(ROOT / '.deps/llvm-runtimes'), 'show',
            BUILDER['REVISION'] + ':' + RELATIVE], text=True,
            env=dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_OPTIONAL_LOCKS='0'))
        path = root / RELATIVE
        path.parent.mkdir(parents=True)
        path.write_text(original)
        return path

    def test_native_header_red_green_idempotency_and_unknown_edit_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            unit = path.parent / 'native_id.cpp'
            unit.write_text('#define TESTING_CXA_GUARD\n#include "cxa_guard_impl.h"\n'
                            'static_assert(+__cxxabiv1::PlatformThreadID != nullptr);\n'
                            'extern "C" uint32_t native_id() {return __cxxabiv1::PlatformThreadID();}\n')
            for patched in (False, True):
                if patched:
                    BUILDER['patch_guard_thread_id'](root)
                    before = path.read_bytes(), path.stat().st_mtime_ns
                    BUILDER['patch_guard_thread_id'](root)
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
                output = root / 'native_id.o'
                command = DRIVER['compiler_command']([
                    '--cxx', '-std=c++20', '-I' + str(path.parent),
                    '-I' + str(SOURCE / 'libcxxabi/src'), '-I' + str(SOURCE / 'libcxx/src'),
                    '-c', str(unit), '-o', str(output)])
                result = subprocess.run(command, capture_output=True, text=True)
                if not patched:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('static assertion failed', result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    symbols = subprocess.check_output(['llvm-nm', '-u', str(output)], text=True)
                    self.assertIn(' U pthread_getthreadid_np\n', symbols)
                    self.assertNotIn(' U syscall\n', symbols)
            path.write_text(path.read_text().replace('const int id = ::pthread_getthreadid_np();', 'unknown_owned_edit();'))
            before = path.read_bytes(), path.stat().st_mtime_ns
            with self.assertRaisesRegex(RuntimeError, 'guard thread ID drift'):
                BUILDER['patch_guard_thread_id'](root)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_actual_native_cxa_guard_unit_no_gc_link_imports_real_thread_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            BUILDER['patch_guard_thread_id'](root)
            unit = path.parent / 'cxa_guard.cpp'
            unit.write_bytes((SOURCE / 'libcxxabi/src/cxa_guard.cpp').read_bytes())
            main = root / 'main.cpp'
            main.write_text('extern "C" int __cxa_guard_acquire(unsigned long long*);\n'
                            'int main(){unsigned long long guard=0;return __cxa_guard_acquire(&guard);}\n')
            obj = root / 'cxa_guard.cpp.o'
            includes = ['-I' + str(SOURCE / 'libcxxabi/src'), '-I' + str(SOURCE / 'libcxx/src')]
            compiled = subprocess.run(DRIVER['compiler_command']([
                '--cxx', '-std=c++20', *includes, '-c', str(unit), '-o', str(obj)]), capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            symbols = subprocess.check_output(['llvm-nm', str(obj)], text=True)
            self.assertIn(' T __cxa_guard_acquire\n', symbols)
            self.assertIn(' U pthread_getthreadid_np\n', symbols)
            archive = root / 'guard.a'
            subprocess.run(['llvm-ar', 'rcs', str(archive), str(obj)], check=True)
            proof = BUILDER['verify_guard_provider'](archive)
            self.assertTrue(proof['code_bodies_verified'])
            self.assertFalse(proof['console_tested'])
            bad = root / 'bad/cxa_guard.cpp.o'
            bad.parent.mkdir()
            subprocess.run(['llvm-objcopy', '--redefine-sym',
                            'pthread_getthreadid_np=untrusted_thread_id', str(obj), str(bad)], check=True)
            bad_archive = root / 'bad.a'
            subprocess.run(['llvm-ar', 'rcs', str(bad_archive), str(bad)], check=True)
            with self.assertRaisesRegex(RuntimeError, 'genuine thread-ID import'):
                BUILDER['verify_guard_provider'](bad_archive)
            exe = root / 'guard.elf'
            linked = subprocess.run(DRIVER['compiler_command']([
                '--cxx', '-std=c++20', str(main), str(obj), '-Wl,--no-gc-sections',
                '-o', str(exe)]), capture_output=True, text=True)
            self.assertEqual(linked.returncode, 0, linked.stderr)
            symbols = subprocess.check_output(['llvm-nm', '-D', str(exe)], text=True)
            self.assertIn(' U pthread_getthreadid_np\n', symbols)

    def test_host_contention_abort_retry_recursive_and_invalid_id_are_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            BUILDER['patch_guard_thread_id'](root)
            (root / 'pthread_np.h').write_text('extern "C" int pthread_getthreadid_np(void);\n')
            exe = root / 'guard'
            includes = [root, path.parent, ROOT / '.deps/libcxx-homebrew/include/c++/v1',
                        SOURCE / 'libcxxabi/src', SOURCE / 'libcxx/src']
            result = subprocess.run([
                'clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                '-fno-omit-frame-pointer', '-nostdinc++', '-DORBISFOX_HOMEBREW_SDK=1',
                *['-I' + str(directory) for directory in includes],
                str(ROOT / 'tests/homebrew_guard_test.cpp'), '-pthread', '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
