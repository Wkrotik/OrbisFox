# SPDX-License-Identifier: MIT
"""Preserve native CRT constructor ownership; no old init-table linker needed."""
from pathlib import Path
import re
import runpy
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
FETCH = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))
VERIFY = runpy.run_path(str(ROOT / 'scripts/verify-startup.py'))


class HomebrewStartupTest(unittest.TestCase):
    def flags(self):
        FETCH['verify']()
        return ['-std=c++20', '-DORBISFOX_FULL_GECKO', '-DORBISFOX_HOMEBREW_SDK=1',
                '-I' + str(ROOT / 'include'), '-isystem', str(FETCH['DESTINATION'] / 'include')]

    def test_genuine_sdk_crt_preinit_loop_and_native_elf_array(self):
        flags = self.flags()
        sdk = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-sdk.py'))['SDK']
        crt = sdk / 'target/lib/crt1.o'
        body = subprocess.check_output(['llvm-objdump', '-dr', '--disassemble-symbols=_init', str(crt)], text=True)
        self.assertLess(body.index('__preinit_array_start'), body.index('__init_array_start'))
        self.assertGreaterEqual(body.count('callq'), 2)
        start = subprocess.check_output(['llvm-objdump', '-dr', '--disassemble-symbols=_start', str(crt)], text=True)
        # The release compiler inlines _init into _start; inspect the real
        # loop/relocations, not an assumed out-of-line call.
        self.assertLess(start.index('_init_env'), start.index('__preinit_array_start'))
        self.assertLess(start.index('__preinit_array_start'), start.index('__init_array_start'))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / 'startup.o'
            command = DRIVER['compiler_command'](['--cxx', *flags, '-c',
                str(ROOT / 'src/ps4/startup.cpp'), '-o', str(output)])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', str(output)], text=True)
            self.assertNotIn('__orbisfox_initializers', symbols)
            self.assertNotIn('__text_start', symbols)
            executable = root / 'native.elf'
            result = subprocess.run(DRIVER['compiler_command'](['--cxx', *flags,
                str(ROOT / 'tests/homebrew_startup_fixture.cpp'), str(output),
                '-Wl,--gc-sections', '-o', str(executable)]), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            sections = subprocess.check_output(['llvm-readelf', '-SW', str(executable)], text=True)
            self.assertIn('.preinit_array', sections)
            self.assertIn('.init_array', sections)
            self.assertNotIn('.orbisfox.startup_entry', sections)
            report = VERIFY['verify'](executable, sdk='homebrew')
            self.assertEqual(len(report['preinitializers']), 1)
            self.assertTrue(report['initializers'])
            self.assertFalse(report['console_startup_verified'])
            self.assertFalse(report['console_cpp_shutdown_verified'])
            data = bytearray(executable.read_bytes())
            invalid = root / 'bad-entry.elf'
            struct.pack_into('<Q', data, 24, int(report['dispatcher'], 16))
            invalid.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'real PIE CRT entry'):
                VERIFY['verify'](invalid, sdk='homebrew')
            data = bytearray(executable.read_bytes())
            header = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
            changed = False
            for i in range(header[12]):
                section = struct.unpack_from('<IIQQQQIIQQ', data, header[6] + i * header[11])
                if section[1] == 6:
                    for offset in range(section[4], section[4] + section[5], 16):
                        tag, value = struct.unpack_from('<QQ', data, offset)
                        if tag == 33:
                            self.assertEqual(value, 8)
                            struct.pack_into('<Q', data, offset + 8, 16)
                            changed = True
            self.assertTrue(changed)
            invalid = root / 'bad-preinit-size.elf'
            invalid.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'dynamic array bounds'):
                VERIFY['verify'](invalid, sdk='homebrew')
            for array_tag, target, message in (
                    (25, int(report['dispatcher'], 16), 'execute more than once'),
                    (32, int(report['dispatcher'], 16) + 1, 'real relocated code body'),
                    (32, None, 'real relocated code body')):
                data = bytearray(executable.read_bytes())
                table_address = None
                elf_sections = [struct.unpack_from('<IIQQQQIIQQ', data, header[6] + i * header[11])
                                for i in range(header[12])]
                for section in elf_sections:
                    if section[1] == 6:
                        for offset in range(section[4], section[4] + section[5], 16):
                            tag, value = struct.unpack_from('<QQ', data, offset)
                            if tag == array_tag:
                                table_address = value
                self.assertIsNotNone(table_address)
                changed = False
                for section in elf_sections:
                    if section[1] == 4:
                        for offset in range(section[4], section[4] + section[5], section[9]):
                            address, info, _ = struct.unpack_from('<QQq', data, offset)
                            if address == table_address and info & 0xffffffff == 8:
                                if target is None:
                                    struct.pack_into('<Q', data, offset + 8, info & ~0xffffffff)
                                    for owner in elf_sections:
                                        if owner[2] & 2 and owner[3] <= table_address < owner[3] + owner[5]:
                                            struct.pack_into('<Q', data, owner[4] + table_address - owner[3],
                                                             int(report['dispatcher'], 16))
                                else:
                                    struct.pack_into('<q', data, offset + 16, target)
                                changed = True
                self.assertTrue(changed)
                invalid = root / f'bad-array-{array_tag}.elf'
                invalid.write_bytes(data)
                with self.assertRaisesRegex(ValueError, message):
                    VERIFY['verify'](invalid, sdk='homebrew')
            symbols = subprocess.check_output(['llvm-nm', '--defined-only', str(executable)], text=True)
            address = int(next(line.split()[0] for line in symbols.splitlines()
                               if line.split()[1:] == ['T', 'orbisfox_startup_dispatch']), 16)
            dump = subprocess.check_output(['llvm-readelf', '-x', '.preinit_array', str(executable)], text=True)
            data = bytes.fromhex(''.join(match.group(1).replace(' ', '') for match in re.finditer(
                r'^\s*0x[0-9a-f]+\s+((?:[0-9a-f]{8} +){1,4})', dump, re.MULTILINE)))
            if data != struct.pack('<Q', address):
                # PIE uses a zero slot plus an explicit RELA addend. Resolve
                # that pointer rather than mistaking the on-disk zero for NULL.
                self.assertEqual(data, bytes(8))
                row = next(line.split() for line in sections.splitlines() if '.preinit_array ' in line)
                start = int(row[row.index('.preinit_array') + 2], 16)
                relocations = subprocess.check_output(['llvm-readelf', '-rW', str(executable)], text=True)
                matches = [line.split() for line in relocations.splitlines()
                           if line.split() and re.fullmatch(r'[0-9a-f]{16}', line.split()[0])
                           and int(line.split()[0], 16) == start]
                self.assertEqual(len(matches), 1, relocations)
                self.assertIn('R_X86_64_RELATIVE', matches[0])
                self.assertEqual(int(matches[0][-1], 16), address)

    def test_host_crt_runs_preinit_once_before_cpp_ctors_without_changing_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for enabled in (0, 1):
                executable = root / f'host-{enabled}'
                result = subprocess.run(['clang++', *self.flags(), f'-DDIAGNOSTICS={enabled}',
                    '-fsanitize=address,undefined', str(ROOT / 'src/ps4/startup.cpp'),
                    str(ROOT / 'tests/homebrew_startup_fixture.cpp'), '-o', str(executable)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run([str(executable)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
