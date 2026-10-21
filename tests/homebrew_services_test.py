# SPDX-License-Identifier: MIT
"""Service declarations remain separate from the SDK's native POSIX ABI."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
FETCH = runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
LOCAL = ROOT / '.deps/OpenOrbis/PS4Toolchain'


class HomebrewServicesTest(unittest.TestCase):
    def bundle(self, destination):
        if not LOCAL.is_dir():
            self.skipTest('Pinned public API headers not cached locally')
        # Tests never fetch or replace dependencies. Production may fetch each
        # bounded, pinned public file explicitly; no SDK runtime is copied.
        with patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network')):
            return FETCH['fetch'](destination, LOCAL)

    def test_pinned_inventory_idempotency_and_no_posix_or_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'headers'
            report = self.bundle(dest)
            self.assertEqual(len(report['git_blobs']), 22)  # 21 headers + GPL LICENSE
            self.assertTrue(all(name == 'LICENSE' or name.startswith('include/orbis/')
                                for name in report['git_blobs']))
            before = {p.relative_to(dest): (p.read_bytes(), p.stat().st_mtime_ns)
                      for p in dest.rglob('*') if p.is_file()}
            self.assertEqual(self.bundle(dest), report)
            after = {p.relative_to(dest): (p.read_bytes(), p.stat().st_mtime_ns)
                     for p in dest.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            poison = dest / 'include/stdlib.h'
            poison.write_text('must not shadow the native SDK')
            with self.assertRaisesRegex(RuntimeError, 'inventory changed'):
                FETCH['verify'](dest)
            poison.unlink()
            header = dest / 'include/orbis/Pad.h'
            header.write_bytes(header.read_bytes() + b'\nunknown edit\n')
            with self.assertRaisesRegex(RuntimeError, 'declaration changed'):
                self.bundle(dest)
            self.assertTrue(header.read_bytes().endswith(b'unknown edit\n'))

    def test_existing_unowned_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            marker = dest / 'private-marker'
            marker.write_bytes(b'keep')
            with self.assertRaisesRegex(RuntimeError, 'inventory changed'):
                FETCH['fetch'](dest, LOCAL)
            self.assertEqual(marker.read_bytes(), b'keep')

    def test_actual_native_service_sources_compile_with_native_posix_types(self):
        if not (ROOT / '.deps/libcxx-homebrew/lib/libc++.a').is_file():
            self.skipTest('Native C++ runtime not built')
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'headers'
            self.bundle(dest)
            flags = ['--cxx', '-std=c++20', '-DORBISFOX_FULL_GECKO', '-D__ORBIS__',
                     '-I' + str(ROOT / 'include'), '-isystem', str(dest / 'include')]
            abi = Path(tmp) / 'abi.cpp'
            abi.write_text('''#include <pthread.h>
#include <sys/stat.h>
#include <orbis/libkernel.h>
#include <orbis/Pad.h>
#include <orbis/ImeDialog.h>
static_assert(sizeof(wchar_t)==2);
static_assert(sizeof(OrbisPthreadOnce)==16 && sizeof(OrbisPthreadMutex)==8);
static_assert(sizeof(struct stat)==120);
''')
            sources = [abi] + [ROOT / 'src/ps4' / name for name in (
                'modules.cpp', 'services.cpp', 'native_network.cpp', 'native_keyboard.cpp',
                'native_audio.cpp', 'videoout.cpp', 'run_logs.cpp', 'native_jit.cpp',
                'native_cpu.cpp', 'sdk_heap_memory.cpp', 'platform.cpp', 'startup.cpp')]
            for number, source in enumerate(sources):
                with self.subTest(source=source.name):
                    command = DRIVER['compiler_command']([*flags, '-c', str(source),
                                                          '-o', str(Path(tmp) / f'{number}.o')])
                    result = subprocess.run(command, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
