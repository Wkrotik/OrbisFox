# SPDX-License-Identifier: MIT
"""Native SDK libevent feature gates and private embedded RNG names."""
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
LIBEVENT = SOURCE / 'ipc/chromium/src/third_party/libevent'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-layout.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
REVISION = runpy.run_path(str(ROOT / 'scripts/configure-gecko-layout.py'))['REVISION']
CONFIG = ROOT / 'gecko/ipc/chromium/src/third_party/libevent/orbis/event2/event-config.h'


class HomebrewLibeventTest(unittest.TestCase):
    def fixture(self, root):
        base = root / 'ipc/chromium/src/third_party/libevent'
        (base / 'orbis/event2').mkdir(parents=True)
        (base / 'bsd/event2').mkdir(parents=True)
        shutil.copy2(CONFIG, base / 'orbis/event2/event-config.h')
        shutil.copy2(LIBEVENT / 'bsd/event2/event-config.h', base / 'bsd/event2/event-config.h')
        shutil.copy2(LIBEVENT / 'arc4random.c', base / 'arc4random.c')
        original = subprocess.check_output(['git', '-C', str(SOURCE), 'show', REVISION +
                     ':ipc/chromium/src/third_party/libevent/evutil_rand.c'])
        (base / 'evutil_rand.c').write_bytes(original)
        return base

    def test_native_headers_use_private_rng_without_touching_entropy_implementation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self.fixture(root)
            path = base / 'evutil_rand.c'
            entropy = (base / 'arc4random.c').read_bytes()
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_libevent_rng_names'](root)
                    before = path.read_bytes(), path.stat().st_mtime_ns
                    PATCH['patch_native_libevent_rng_names'](root)
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
                    self.assertEqual((base / 'arc4random.c').read_bytes(), entropy)
                probe = base / 'rng-probe.c'
                probe.write_text(path.read_text() + '''
#ifdef arc4random_buf
#error RNG macro leaked into subsequent unified units
#endif
#ifdef arc4random_addrandom
#error RNG macro leaked into subsequent unified units
#endif
''')
                args = ['-std=gnu11', '-D_GNU_SOURCE', '-D_BSD_SOURCE',
                        '-I' + str(base / 'orbis'), '-I' + str(LIBEVENT / 'include'),
                        '-I' + str(LIBEVENT / 'compat'), '-I' + str(LIBEVENT),
                        '-c', str(probe), '-o', str(root / 'rng.o')]
                result = subprocess.run(DRIVER['compiler_command'](args), capture_output=True, text=True)
                if not patched:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("static declaration of 'arc4random_", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    symbols = subprocess.check_output(['llvm-nm', str(root / 'rng.o')], text=True)
                    for name in ('arc4random_buf', 'arc4random_addrandom'):
                        self.assertIn(' t orbis_libevent_' + name + '\n', symbols)
                        self.assertNotIn(' U ' + name + '\n', symbols)
                        self.assertNotIn(' T ' + name + '\n', symbols)

    def test_native_pipe_fallback_retains_rng_backend_and_legacy_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self.fixture(root)
            probe = root / 'config.c'
            probe.write_text('#include "event2/event-config.h"\n')
            for native in (False, True):
                args = ['-E', '-dM', '-I' + str(base / 'orbis'), str(probe)]
                if not native:
                    args.insert(0, '-UORBISFOX_HOMEBREW_SDK')
                result = subprocess.run(DRIVER['compiler_command'](args), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                if native:
                    self.assertNotIn('#define EVENT__HAVE_PIPE2 ', result.stdout)
                else:
                    self.assertIn('#define EVENT__HAVE_PIPE2 1', result.stdout)
                for feature in ('ARC4RANDOM', 'ARC4RANDOM_ADDRANDOM', 'ARC4RANDOM_BUF', 'KQUEUE', 'GETRANDOM'):
                    self.assertNotIn('#define EVENT__HAVE_' + feature + ' ', result.stdout)


if __name__ == '__main__':
    unittest.main()
