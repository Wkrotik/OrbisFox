#!/usr/bin/env python3
"""Exactly one real demangler across the Orbis stack-walk capability matrix."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
FALLBACK = ROOT / 'gecko/mozglue/misc/DemangleSymbol_orbis.cpp'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
GUARD = ('#if !(defined(HAVE_DLADDR) && HAVE_DLADDR && \\\n'
         '      defined(HAVE__UNWIND_BACKTRACE) && HAVE__UNWIND_BACKTRACE)')


class HomebrewDemangleTest(unittest.TestCase):
    def test_actual_provider_and_fallback_have_one_definition_and_real_demangling(self):
        text = (SOURCE / 'mozglue/misc/StackWalk.cpp').read_text()
        old = '#  if defined(MOZ_DEMANGLE_SYMBOLS)'
        native = old + ' || defined(MOZ_ORBIS_HOMEBREW_SDK)'
        # Exercise the actual native adaptation with no unrelated demangling
        # feature define; merely choosing the provider must not empty its body.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'mozglue/misc/StackWalk.cpp'
            path.parent.mkdir(parents=True)
            path.write_text(text.replace(native, old))
            PATCH['patch_native_demangling'](temp)
            text = path.read_text()
            self.assertEqual(text.count(native), 2)
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            PATCH['patch_native_demangling'](temp)
            self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
            path.write_text(text.replace(native, '#  if 0', 1))
            with self.assertRaisesRegex(RuntimeError, 'drift'):
                PATCH['patch_native_demangling'](temp)
        start = text.index('namespace mozilla {', text.index('#elif HAVE_DLADDR &&'))
        stop = text.index('}  // namespace mozilla', start) + len('}  // namespace mozilla')
        provider = ('#include <cxxabi.h>\n#include <stdlib.h>\n#include <string.h>\n'
                    '#if HAVE_DLADDR && HAVE__UNWIND_BACKTRACE\n' + text[start:stop] + '\n#endif\n')
        fallback = FALLBACK.read_text()
        self.assertEqual(fallback.count(GUARD), 1)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'StackWalk.h').write_text('namespace mozilla { void DemangleSymbol(const char*, char*, int); }\n')
            (root / 'provider.cpp').write_text(provider)
            (root / 'fallback.cpp').write_text(fallback)
            (root / 'caller.cpp').write_text('''#include "StackWalk.h"
#include <cassert>
#include <cstring>
int main() {
  for (int i = 0; i < 32; ++i) {
    char result[128] = {};
    mozilla::DemangleSymbol("_Z3foov", result, sizeof(result));
    assert(std::strcmp(result, "foo()") == 0);
  }
}
''')
            for native in (False, True):
                for dladdr in (0, 1):
                    for unwind in (0, 1):
                        with self.subTest(native=native, dladdr=dladdr, unwind=unwind):
                            flags = ['-std=c++20', '-I' + str(root),
                                     '-DMOZ_ORBIS_HOMEBREW_SDK=1',
                                     '-DHAVE_DLADDR=' + str(dladdr),
                                     '-DHAVE__UNWIND_BACKTRACE=' + str(unwind)]
                            output = root / ('demangle-' + str(native) + str(dladdr) + str(unwind))
                            args = [*flags, str(root / 'provider.cpp'), str(root / 'fallback.cpp'),
                                    str(root / 'caller.cpp'), '-o', str(output)]
                            command = DRIVER['compiler_command'](['--cxx', *args]) if native else ['clang++', *args]
                            result = subprocess.run(command, capture_output=True, text=True)
                            self.assertEqual(result.returncode, 0, result.stderr)
                            symbols = subprocess.check_output(['llvm-nm', '--defined-only', '--demangle', str(output)], text=True)
                            definitions = [line for line in symbols.splitlines()
                                if line.endswith(' mozilla::DemangleSymbol(char const*, char*, int)')]
                            self.assertEqual(len(definitions), 1)
                            if not native:
                                subprocess.run([str(output)], check=True)
                # The original unconditional fallback reproduces the strict
                # duplicate-provider failure when native unwinding is available.
                (root / 'original.cpp').write_text(fallback.replace(GUARD, '#if 1'))
                args = ['-std=c++20', '-I' + str(root),
                        '-DMOZ_ORBIS_HOMEBREW_SDK=1',
                        '-DHAVE_DLADDR=1', '-DHAVE__UNWIND_BACKTRACE=1',
                        str(root / 'provider.cpp'), str(root / 'original.cpp'),
                        str(root / 'caller.cpp'), '-o', str(root / 'duplicate')]
                command = DRIVER['compiler_command'](['--cxx', *args]) if native else ['clang++', *args]
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue('duplicate symbol' in result.stderr or 'multiple definition' in result.stderr,
                                result.stderr)


if __name__ == '__main__':
    unittest.main()
