# SPDX-License-Identifier: MIT
"""Disabled configure options must not leak into #ifdef native/GPU code."""
import ast
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))


def callback(name, old=False):
    tree = ast.parse((ROOT / 'gecko/orbisfox/moz.configure').read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    function.decorator_list = []
    if old:
        function.body = ast.parse('return bool(value)').body
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {}
    exec(compile(module, 'orbis-options', 'exec'), namespace)
    return namespace[name]


class HomebrewOptionsTest(unittest.TestCase):
    def test_both_disabled_callbacks_return_none_not_empty_define(self):
        for name in ('orbis_mesa', 'orbis_homebrew_sdk'):
            option = callback(name)
            self.assertIsNone(option(False))
            self.assertIsNone(option(()))
            self.assertIs(option(('enabled',)), True)
            self.assertIs(callback(name, old=True)(False), False)

    def test_actual_sdk_preprocessor_original_false_leaks_gpu_but_none_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'guards.c'
            source.write_text('''#include <pthread.h>
#include <pthread_np.h>
extern void *eglGetProcAddress(const char *);
int guard_selection(void) {
 int value=0;
#ifdef MOZ_ORBIS_HOMEBREW_SDK
 value=pthread_getthreadid_np();
#endif
#ifdef MOZ_ORBIS_MESA
 value += eglGetProcAddress("glReadPixels") != 0;
#endif
 return value;
}
''')
            for old in (True, False):
                for mesa in (False, True):
                    for native in (False, True):
                        definitions = []
                        for name, option, value in (
                                ('MOZ_ORBIS_MESA', 'orbis_mesa', mesa),
                                ('MOZ_ORBIS_HOMEBREW_SDK', 'orbis_homebrew_sdk', native)):
                            selected = callback(option, old=old)(value)
                            # Gecko's set_define contract: False is a defined
                            # valueless macro; only None leaves it undefined.
                            if selected is not None:
                                definitions.append('-D' + name + ('=1' if selected else '='))
                        obj = root / 'guards.o'
                        result = subprocess.run(DRIVER['compiler_command']([
                            *definitions, '-c', str(source), '-o', str(obj)]), capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        symbols = subprocess.check_output(['llvm-nm', '-u', str(obj)], text=True)
                        self.assertEqual(' U eglGetProcAddress\n' in symbols, old or mesa)
                        self.assertEqual(' U pthread_getthreadid_np\n' in symbols, old or native)


if __name__ == '__main__':
    unittest.main()
