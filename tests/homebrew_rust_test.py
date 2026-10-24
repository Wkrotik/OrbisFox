# SPDX-License-Identifier: MIT
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP = runpy.run_path(str(ROOT / 'scripts/bootstrap-homebrew-rust.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
VERIFY = runpy.run_path(str(ROOT / 'scripts/verify-rust-abi.py'))


def snapshot(paths):
    return {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths}


class HomebrewRustTest(unittest.TestCase):
    def native_runtime(self):
        report = ROOT / 'build/rust-homebrew/build-report.json'
        if not report.is_file():
            self.skipTest('Native Rust runtime not built; run build-homebrew-rust.py')
        data = json.loads(report.read_text())
        self.assertEqual(data['result'], 0)
        revision = hashlib.sha256(b''.join(p.read_bytes() for p in (
            ROOT / 'scripts/bootstrap-homebrew-rust.py', ROOT / 'scripts/homebrew-rustc.py',
            ROOT / 'targets/x86_64-scei-ps4.json'))).hexdigest()
        self.assertEqual(data['abi_revision'], revision, 'Rebuild changed native Rust sources first')
        return data

    def test_old_target_rejected_but_project_path_is_not_a_target(self):
        for value in ('x86_64-orbis-freebsd', str(ROOT / 'targets/x86_64-orbis-freebsd.json')):
            result = subprocess.run([str(ROOT / 'scripts/homebrew-rustc.py'), '--target=' + value, '--print=cfg'],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Old SDK Rust target', result.stderr)
        result = subprocess.run([str(ROOT / 'scripts/homebrew-rustc.py'),
                                 '--target=' + str(ROOT / 'targets/x86_64-scei-ps4.json'), '--print=cfg'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('target_vendor="scei"', result.stdout)
        self.assertIn('target_os="freebsd"', result.stdout)

    def test_router_fails_closed_and_native_target_list_is_available(self):
        router = str(ROOT / 'scripts/orbis-rustc.py')
        result = subprocess.run([router, '--version'], env=dict(os.environ, ORBISFOX_SDK='typo'),
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unknown ORBISFOX_SDK', result.stderr)
        result = subprocess.run([router, '--print=target-list'], env=dict(os.environ, ORBISFOX_SDK='homebrew'),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('x86_64-scei-ps4', result.stdout.splitlines())

    def test_native_source_patches_byte_and_mtime_stable_without_old_writes(self):
        self.native_runtime()
        library = ROOT / '.deps/rust-homebrew-sysroot/lib/rustlib/src/rust/library'
        native = list((library / 'vendor/libc-0.2.189').rglob('*.rs'))
        native += list((library / 'std/src/sys').rglob('*.rs'))
        native += [library / 'std/src/os/fd/owned.rs']
        native += [library / 'backtrace/src/symbolize/mod.rs']
        old = ROOT / '.deps/rust-sysroot/lib/rustlib/src/rust/library'
        sentinels = [old / 'std/src/sys/thread/unix.rs',
                     old / 'vendor/libc-0.2.189/src/unix/bsd/freebsdlike/mod.rs']
        before, original = snapshot(native), snapshot(sentinels)
        BOOTSTRAP['bootstrap']()
        self.assertEqual(before, snapshot(native))
        self.assertEqual(original, snapshot(sentinels))

    def test_actual_native_cpp_rust_abi_and_complete_link(self):
        runtime = self.native_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cpp, joined, elf = tmp / 'abi.o', tmp / 'joined.o', tmp / 'link.elf'
            command = DRIVER['compiler_command'](['--cxx', '-std=c++20', '-I' + str(ROOT / 'include'),
                        '-c', str(ROOT / 'src/ps4/rust_runtime.cpp'), '-o', str(cpp)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run(['ld.lld', '-r', cpp, '--whole-archive', ROOT / 'build/rust-homebrew/liborbisfox.a',
                            '--no-whole-archive', '-o', joined], check=True, capture_output=True)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                VERIFY['verify'](joined, sdk_name='native SDK')
            self.assertIn('all 32 audited ABI', output.getvalue())
            result = subprocess.run(DRIVER['compiler_command'](['--cxx', '-std=c++20',
                '-I' + str(ROOT / 'include'), '-Wl,--gc-sections',
                str(ROOT / 'tests/homebrew_rust_link.cpp'), str(cpp), runtime['staticlib'], '-o', str(elf)]),
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', '--defined-only', elf], text=True)
            self.assertIn('orbisfox_rust_native_threads_probe', symbols)
            self.assertIn('orbisfox_rust_check_abi', symbols)
            self.assertNotIn('orbisfox_sdk_malloc_state', symbols)
            undefined = subprocess.check_output(['llvm-nm', '--undefined-only', elf], text=True)
            self.assertNotIn('dl_iterate_phdr', undefined)
            self.assertNotIn('pthread_setname_np', undefined)
            self.assertNotIn('clock_nanosleep', undefined)
            self.assertIn('pthread_set_name_np', undefined)
            self.assertIn('malloc', undefined)


if __name__ == '__main__':
    unittest.main()
