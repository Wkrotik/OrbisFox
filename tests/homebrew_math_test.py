# SPDX-License-Identifier: MIT
"""Native FFVPX links actual libc math, never a fabricated libm archive."""
import ast
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))


class HomebrewMathTest(unittest.TestCase):
    def fixture(self, root):
        files = []
        for library in ('libavutil', 'libavcodec'):
            relative = 'media/ffvpx/' + library + '/moz.build'
            original = subprocess.check_output(['git', '-C', str(SOURCE), 'show',
                                               PATCH['REVISION'] + ':' + relative], text=True)
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(original)
            files.append(path)
        return files

    def math_libs(self, path, sdk, os_target, library='m', expected_blocks=1):
        tree = ast.parse(path.read_text())
        selections = [node for node in tree.body if isinstance(node, ast.If)
                      and len(node.body) == 1 and isinstance(node.body[0], ast.AugAssign)
                      and isinstance(node.body[0].target, ast.Name) and node.body[0].target.id == 'OS_LIBS'
                      and isinstance(node.body[0].value, ast.List)
                      and all(isinstance(item, ast.Constant) for item in node.body[0].value.elts)
                      and [item.value for item in node.body[0].value.elts] == [library]]
        self.assertEqual(len(selections), expected_blocks)
        namespace = {'CONFIG': {'OS_TARGET': os_target, 'OS_ARCH': os_target,
                                'MOZ_ORBIS_HOMEBREW_SDK': sdk}, 'OS_LIBS': []}
        module = ast.fix_missing_locations(ast.Module(body=selections, type_ignores=[]))
        exec(compile(module, str(path), 'exec'), namespace)
        return namespace['OS_LIBS']

    def test_original_sdk_link_fails_then_genuine_math_imports_link_without_gc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.fixture(root)
            main = root / 'math.c'
            main.write_text('''#include <math.h>
volatile double input = 1.25;
int main(void) {
 double x=input;
 volatile double result=cos(x)+sin(x)+sqrt(x)+pow(x,2.0)+floor(x)+ceil(x)+log2(x)+exp2(x)+ldexp(x,2);
 return result==0.0;
}
''')
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_ffvpx_math'](root)
                for path in paths:
                    libraries = self.math_libs(path, True, 'FreeBSD')
                    self.assertEqual(libraries, [] if patched else ['m'])
                    exe = root / 'math.elf'
                    result = subprocess.run(DRIVER['compiler_command']([
                        '-fno-builtin', str(main), '-Wl,--no-gc-sections',
                        *['-l' + name for name in libraries], '-o', str(exe)]), capture_output=True, text=True)
                    if not patched:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('unable to find library -lm', result.stderr)
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        symbols = subprocess.check_output(['llvm-nm', '-D', str(exe)], text=True)
                        for name in ('sin', 'cos', 'sqrt', 'pow', 'floor', 'ceil', 'log2', 'exp2', 'ldexp'):
                            self.assertIn(' U ' + name + '\n', symbols)
                        dynamic = subprocess.check_output(['llvm-readelf', '-d', str(exe)], text=True)
                        self.assertIn('[libSceLibcInternal.sprx]', dynamic)
                        self.assertNotIn('[libm', dynamic)
                for path in paths:
                    self.assertEqual(self.math_libs(path, False, 'Linux'), ['m'])
                    self.assertEqual(self.math_libs(path, False, 'FreeBSD'), ['m'])
                    self.assertEqual(self.math_libs(path, False, 'WINNT'), [])

    def test_engine_system_library_selection_and_atomic_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for relative in ('js/src/build/moz.build', 'toolkit/library/moz.build'):
                path = root / relative
                path.parent.mkdir(parents=True)
                path.write_bytes(subprocess.check_output(['git', '-C', str(SOURCE), 'show',
                                                         PATCH['REVISION'] + ':' + relative]))
                files.append(path)
            self.assertEqual(self.math_libs(files[0], True, 'FreeBSD'), ['m'])
            self.assertEqual(self.math_libs(files[1], True, 'FreeBSD', 'util', 2), ['util', 'util'])
            original = [path.read_text() for path in files]
            files[1].write_text(original[1].replace('"util",', '"unknown_owned_library",', 1))
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
            with self.assertRaisesRegex(RuntimeError, 'engine system library drift'):
                PATCH['patch_native_engine_libraries'](root)
            self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in files], before)
            for path, text in zip(files, original):
                path.write_text(text)
            PATCH['patch_native_engine_libraries'](root)
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]
            PATCH['patch_native_engine_libraries'](root)
            self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in files], before)
            for sdk in (False, True):
                for os_target in ('WINNT', 'Linux', 'FreeBSD', 'Darwin'):
                    math = ['m'] if os_target != 'WINNT' and not sdk else []
                    util = ['util', 'util'] if os_target == 'FreeBSD' and not sdk else []
                    self.assertEqual(self.math_libs(files[0], sdk, os_target), math)
                    self.assertEqual(self.math_libs(files[1], sdk, os_target, 'util', 2), util)
            backend = ROOT / 'build/gecko-layout/config/autoconf.mk'
            self.assertIn('-Wl,-z,defs', backend.read_text())

    def test_both_modules_idempotent_and_validate_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.fixture(root)
            original = [path.read_text() for path in paths]
            paths[1].write_text(original[1].replace("OS_LIBS += ['m']", "OS_LIBS += ['unknown_owned_lib']"))
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
            with self.assertRaisesRegex(RuntimeError, 'FFVPX math library drift'):
                PATCH['patch_native_ffvpx_math'](root)
            self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in paths], before)
            for path, text in zip(paths, original):
                path.write_text(text)
            PATCH['patch_native_ffvpx_math'](root)
            before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
            PATCH['patch_native_ffvpx_math'](root)
            self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in paths], before)


if __name__ == '__main__':
    unittest.main()
