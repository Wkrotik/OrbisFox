import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('overlay', ROOT / 'scripts/sdk-overlay.py')
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)

class OverlayTests(unittest.TestCase):
    def test_pthread_attribute_storage_and_alignment(self):
        overlay.generate()
        source = '#include <pthread.h>\n'
        for name in ('mutexattr', 'condattr', 'rwlockattr', 'barrierattr'):
            source += f'static_assert(sizeof(pthread_{name}_t)==8);\n'
            source += f'static_assert(alignof(pthread_{name}_t)==8);\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'abi.cpp'
            path.write_text(source)
            subprocess.run([str(ROOT / 'scripts/orbis-cc.py'), '--cxx', '-std=c++20',
                            '-fsyntax-only', str(path)], check=True)

    def test_unchanged_generation_preserves_dependency_timestamp(self):
        overlay.generate()
        path = ROOT / '.deps/sdk-overlay/bits/alltypes.h'
        before = path.stat().st_mtime_ns
        overlay.generate()
        self.assertEqual(path.stat().st_mtime_ns, before)
        original = (ROOT / '.deps/OpenOrbis/PS4Toolchain/include/bits/alltypes.h').read_text()
        self.assertIn('typedef struct { unsigned __attr; } pthread_mutexattr_t;', original)

if __name__ == '__main__':
    unittest.main()
