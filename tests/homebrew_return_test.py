# SPDX-License-Identifier: MIT
from pathlib import Path
import os
import resource
import runpy
import signal
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
SERVICE = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))
SOURCE = ROOT / 'src/ps4/homebrew_return.cpp'


class HomebrewReturnTest(unittest.TestCase):
    def flags(self):
        SERVICE['verify']()
        return ['-std=c++20', '-O1', '-DORBISFOX_FULL_GECKO', '-DORBISFOX_HOMEBREW_SDK',
                '-I' + str(ROOT / 'include'), '-isystem', str(SERVICE['DESTINATION'] / 'include')]

    def test_actual_native_hook_is_strong_and_uses_real_clock_manager_not_raw_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj = Path(tmp) / 'return.o'
            result = subprocess.run(DRIVER['compiler_command'](['--cxx', *self.flags(),
                '-c', str(SOURCE), '-o', str(obj)]), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', '-C', str(obj)], text=True)
            self.assertRegex(symbols, r'\bT catchReturnFromMain\b')
            self.assertRegex(symbols, r'\bU clock_gettime\b')
            self.assertIn('U orbisfox::request_system_exit()', symbols)
            self.assertRegex(symbols, r'\bU sceKernelUsleep\b')
            for forbidden in ('U exit', 'U _exit', 'U _Exit', 'U __cxa_finalize', 'U atexit'):
                self.assertNotIn(forbidden, symbols)

    def test_real_crt_calls_strong_hook_with_actual_service_loader_no_gc_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / 'main.cpp'
            main.write_text('namespace orbisfox {void log(const char*,...) {}}\nint main(){return 17;}\n')
            executable = root / 'native.elf'
            command = DRIVER['compiler_command'](['--cxx', *self.flags(), str(SOURCE),
                str(ROOT / 'src/ps4/services.cpp'), str(ROOT / 'src/ps4/modules.cpp'),
                str(main), '-Wl,--no-gc-sections', '-o', str(executable)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', str(executable)], text=True)
            self.assertRegex(symbols, r'\bT catchReturnFromMain\b')
            assembly = subprocess.check_output(['llvm-objdump', '-d', '--no-show-raw-insn',
                '--disassemble-symbols=_start,catchReturnFromMain', str(executable)], text=True)
            start = assembly.split('<_start>:', 1)[1].split('Disassembly of section', 1)[0]
            self.assertIn('<main>', start)
            self.assertIn('<catchReturnFromMain>', start)
            self.assertLess(start.index('<main>'), start.index('<catchReturnFromMain>'))
            hook = assembly.split('<catchReturnFromMain>:', 1)[1].split('Disassembly of section', 1)[0]
            self.assertIn('request_system_exit', hook)
            self.assertIn('ud2', hook)
            for forbidden in ('<exit>', '<exit@plt>', '<_exit>', '<__cxa_finalize>'):
                self.assertNotIn(forbidden, hook)

    def test_host_immediate_async_rejected_stuck_and_failed_clock_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'test'
            result = subprocess.run(['clang++', *self.flags(), '-g', '-fsanitize=address,undefined',
                str(SOURCE), str(ROOT / 'tests/homebrew_return_fixture.cpp'), '-o', str(exe)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            env = dict(os.environ)
            env['ASAN_OPTIONS'] = env.get('ASAN_OPTIONS', '') + ':handle_sigill=0'
            for mode in range(8):
                # Expected production fail-fast traps need no retained core.
                def no_core():
                    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                result = subprocess.run([str(exe), str(mode)], capture_output=True, text=True,
                                        timeout=10, env=env, preexec_fn=no_core)
                self.assertEqual(result.returncode, 73 if mode in (0, 7) else -signal.SIGILL,
                                 result.stdout + result.stderr)
                self.assertIn('status=17', result.stderr)
                if mode == 1:
                    self.assertIn('exit rejected', result.stderr)
                if mode in (2, 4):
                    self.assertIn('exit timed out', result.stderr)


if __name__ == '__main__':
    unittest.main()
