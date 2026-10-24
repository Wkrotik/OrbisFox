#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
AUDIT = runpy.run_path(str(ROOT / 'scripts/elf-call-targets.py'))['call_targets']


class HomebrewCallsTest(unittest.TestCase):
    def test_actual_sdk_thunks_bind_imports_not_nearest_symbol_labels(self):
        driver = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            source = temp / 'calls.cpp'
            source.write_text('''#include <pthread.h>
#include <pthread_np.h>
extern "C" __attribute__((noinline)) int fixture_thread_id() {
  return pthread_getthreadid_np();
}
extern "C" __attribute__((noinline)) int fixture_wait(pthread_cond_t* c, pthread_mutex_t* m) {
  return pthread_cond_wait(c, m);
}
int main() { return fixture_thread_id(); }
''')
            elf = temp / 'calls.elf'
            command = driver['compiler_command'](['--cxx', '-std=c++20', '-O0',
                '-Wl,-z,defs', str(source), '-o', str(elf)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            assembly = subprocess.check_output(['llvm-objdump', '-d',
                '--disassemble-symbols=fixture_thread_id,fixture_wait', str(elf)], text=True)
            calls = AUDIT(elf, assembly)
            names = {call['symbol'] for call in calls if call['imported']}
            self.assertIn('pthread_getthreadid_np', names)
            self.assertIn('pthread_cond_wait', names)
            self.assertTrue(all('got' in call for call in calls if call['imported']))
            # A guessed nearest-symbol label must not alter actual bindings.
            misleading = re.sub(r'<[^>]*>', '<syscall>', assembly)
            self.assertEqual(AUDIT(elf, misleading), calls)

            original = elf.read_bytes()
            real = b'pthread_getthreadid_np'
            wrong = b'not_a_thread_id'.ljust(len(real), b'_')
            self.assertIn(real + b'\0', original)
            changed = temp / 'wrong-import.elf'
            changed.write_bytes(original.replace(real + b'\0', wrong + b'\0'))
            bad = AUDIT(changed, assembly)
            bad_names = {call['symbol'] for call in bad if call['imported']}
            self.assertNotIn(real.decode(), bad_names)
            self.assertIn(wrong.decode(), bad_names)

            # Reject disassembly from a different instruction stream.
            lines = assembly.splitlines()
            for i, line in enumerate(lines):
                if re.search(r'\bcallq?\s', line):
                    lines[i] = re.sub(r'(:\s+)[0-9a-f]{2}', r'\g<1>90', line, count=1)
                    break
            else:
                self.fail('Actual SDK fixture did not contain a direct call')
            with self.assertRaisesRegex(ValueError, 'bytes do not match'):
                AUDIT(elf, '\n'.join(lines))
            truncated = temp / 'truncated.elf'
            truncated.write_bytes(original[:63])
            with self.assertRaisesRegex(ValueError, 'out of bounds'):
                AUDIT(truncated, assembly)


if __name__ == '__main__':
    unittest.main()
