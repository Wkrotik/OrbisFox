# SPDX-License-Identifier: MIT
"""Real libclang (not a compiler-driver double) parses the native ABI headers."""
import ctypes as C
import ctypes.util
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
CONFIGURE = runpy.run_path(str(ROOT / 'scripts/configure-gecko-layout.py'))


class CXString(C.Structure):
    _fields_ = [('data', C.c_void_p), ('private_flags', C.c_uint)]


def diagnostics(lib, path, flags):
    signatures = {
        'clang_createIndex': ([C.c_int, C.c_int], C.c_void_p),
        'clang_parseTranslationUnit': ([C.c_void_p, C.c_char_p, C.POINTER(C.c_char_p), C.c_int,
                                       C.c_void_p, C.c_uint, C.c_uint], C.c_void_p),
        'clang_getNumDiagnostics': ([C.c_void_p], C.c_uint),
        'clang_getDiagnostic': ([C.c_void_p, C.c_uint], C.c_void_p),
        'clang_getDiagnosticSeverity': ([C.c_void_p], C.c_uint),
        'clang_getDiagnosticSpelling': ([C.c_void_p], CXString),
        'clang_getCString': ([CXString], C.c_char_p),
        'clang_disposeString': ([CXString], None),
        'clang_disposeDiagnostic': ([C.c_void_p], None),
        'clang_disposeTranslationUnit': ([C.c_void_p], None),
        'clang_disposeIndex': ([C.c_void_p], None),
    }
    for name, (args, result) in signatures.items():
        function = getattr(lib, name)
        function.argtypes, function.restype = args, result
    index = lib.clang_createIndex(0, 0)
    unit = None
    errors = []
    try:
        argv = (C.c_char_p * len(flags))(*(flag.encode() for flag in flags))
        unit = lib.clang_parseTranslationUnit(index, str(path).encode(), argv, len(flags), None, 0, 0)
        if not unit:
            raise RuntimeError('libclang did not create a translation unit')
        for number in range(lib.clang_getNumDiagnostics(unit)):
            diagnostic = lib.clang_getDiagnostic(unit, number)
            try:
                if lib.clang_getDiagnosticSeverity(diagnostic) >= 3:
                    text = lib.clang_getDiagnosticSpelling(diagnostic)
                    try:
                        errors.append(lib.clang_getCString(text).decode())
                    finally:
                        lib.clang_disposeString(text)
            finally:
                lib.clang_disposeDiagnostic(diagnostic)
        return errors
    finally:
        if unit:
            lib.clang_disposeTranslationUnit(unit)
        lib.clang_disposeIndex(index)


class HomebrewBindgenTest(unittest.TestCase):
    def test_actual_libclang_needs_resource_headers_and_parses_native_cpp_abi(self):
        library = ctypes.util.find_library('clang')
        if not library:
            self.skipTest('libclang is not installed')
        if not (ROOT / '.deps/libcxx-homebrew/include/c++/v1').is_dir():
            self.skipTest('Native C++ runtime not built')
        lib = C.CDLL(library)
        flags = ['-x', 'c++', '-std=c++20', *CONFIGURE['native_bindgen_flags']()]
        resource = flags.index('-resource-dir')
        # The failing case deliberately supplies an absent resource directory:
        # reproduces bindgen's missing stddef/intrinsic headers without relying
        # on how this host's libclang guesses its installation prefix.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bindings.cpp'
            path.write_text('''#include <cstddef>
#include <memory_resource>
#include <cmath>
#include <cwchar>
#include <emmintrin.h>
#include <pthread.h>
#include <time.h>
static_assert(sizeof(wchar_t)==2 && sizeof(pthread_once_t)==16);
static_assert(CLOCK_MONOTONIC==4 && CLOCK_PROCESS_CPUTIME_ID==15);
static_assert(sizeof(max_align_t)>=sizeof(long double));
std::pmr::memory_resource* resource;
''')
            absent = flags.copy()
            absent[resource + 1] = str(Path(tmp) / 'missing-resource')
            failures = diagnostics(lib, path, absent)
            self.assertTrue(failures)
            self.assertTrue(any('not found' in error for error in failures), failures)
            self.assertEqual(diagnostics(lib, path, flags), [])


if __name__ == '__main__':
    unittest.main()
