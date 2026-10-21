# SPDX-License-Identifier: MIT
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
FETCH = runpy.run_path(str(ROOT / 'scripts/fetch-native-font-header.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))


class HomebrewFontTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FETCH['fetch']()

    def test_exact_public_header_inventory_hash_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'include'
            with patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected download')):
                FETCH['fetch'](root, local=FETCH['DESTINATION'])
                before = {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in root.rglob('*') if p.is_file()}
                FETCH['fetch'](root)
                after = {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                         for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            header = root / FETCH['RELATIVE']
            header.write_bytes(header.read_bytes() + b'\nunknown edit\n')
            modified = header.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'hash changed'):
                FETCH['fetch'](root)
            self.assertEqual(header.read_bytes(), modified)

    def test_real_native_chrome_compiles_without_old_sdk_include_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'chrome.o'
            flags = ['--cxx', '-std=c++20', '-O1', '-DORBISFOX_FULL_GECKO',
                     '-I' + str(ROOT / 'include'), '-I' + str(FETCH['DESTINATION']),
                     '-c', str(ROOT / 'src/native_chrome.cpp'), '-o', str(output)]
            command = DRIVER['compiler_command'](flags)
            self.assertNotIn('OpenOrbis/PS4Toolchain', ' '.join(command))
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreater(output.stat().st_size, 1000)


if __name__ == '__main__':
    unittest.main()
