# SPDX-License-Identifier: MIT
"""C++20 Maybe storage with the genuine nontrivial FreeBSD std::pair ABI."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
FILES = ('mfbt/MaybeStorageBase.h', 'mfbt/Maybe.h')


class HomebrewMaybeTest(unittest.TestCase):
    def fixture(self, root):
        for name in FILES:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(subprocess.check_output(['git', '-C', str(SOURCE), 'show',
                                                      PATCH['REVISION'] + ':' + name]))
            link = root / 'include/mozilla' / path.name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(path)

    def test_storage_idempotency_and_atomic_drift_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            PATCH['patch_maybe_constexpr'](root)
            before = {name: ((root / name).read_bytes(), (root / name).stat().st_mtime_ns) for name in FILES}
            PATCH['patch_maybe_constexpr'](root)
            self.assertEqual(before, {name: ((root / name).read_bytes(), (root / name).stat().st_mtime_ns)
                                      for name in FILES})
            # Reset only the owned scratch files; exercise all-or-nothing writes.
            for name in FILES:
                (root / name).write_bytes(subprocess.check_output(['git', '-C', str(SOURCE), 'show',
                                                                  PATCH['REVISION'] + ':' + name]))
            path = root / FILES[1]
            path.write_text(path.read_text().replace('  ~MaybeStorage()', '  ~UnknownEdit()'))
            before = {name: (root / name).read_bytes() for name in FILES}
            with self.assertRaisesRegex(RuntimeError, 'constexpr Maybe storage drift'):
                PATCH['patch_maybe_constexpr'](root)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in FILES})

    def test_native_dom_incomplete_union_destructors_remain_lazy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            main = root / 'dom.cpp'
            main.write_text('#include "mozilla/dom/LocalizationBinding.h"\n')
            flags = ['--cxx', '-std=c++20', '-D__ORBIS__', '-DNDEBUG', '-DTRIMMED',
                     '-DMOZILLA_INTERNAL_API', '-DIMPL_LIBXUL', '-DMOZ_HAS_MOZGLUE',
                     '-fno-exceptions', '-fno-rtti', '-fno-sized-deallocation', '-fno-aligned-new',
                     '-include', str(ROOT / 'build/gecko-layout/mozilla-config.h'),
                     '-I' + str(root / 'include'),
                     '-I' + str(ROOT / 'build/gecko-layout/dist/include'),
                     '-I' + str(ROOT / 'build/gecko-layout/dist/include/nspr'),
                     '-I' + str(SOURCE / 'js/src'), '-fsyntax-only', str(main)]
            for adapted in (False, True):
                if adapted:
                    PATCH['patch_maybe_constexpr'](root)
                result = subprocess.run(DRIVER['compiler_command'](flags), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_language_id_constant_evaluation_and_runtime_destruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            main = root / 'test.cpp'
            main.write_text('''#include "util/LanguageId.h"
#include <cstdlib>
#include <type_traits>
#ifdef ORBISFOX_HOMEBREW_SDK
static_assert(!std::is_trivially_copy_constructible_v<std::pair<int,int>>);
#endif
struct NonTrivialCopy {
 int value;
 constexpr NonTrivialCopy(int n):value(n){}
 constexpr NonTrivialCopy(const NonTrivialCopy& other):value(other.value){}
};
static_assert(!std::is_trivially_copy_constructible_v<NonTrivialCopy>);
static_assert(std::is_trivially_destructible_v<NonTrivialCopy>);
// Preserve the original nontrivial storage destructor/copy ABI classification.
static_assert(!std::is_trivially_destructible_v<mozilla::Maybe<NonTrivialCopy>>);
static_assert(!std::is_trivially_copy_constructible_v<mozilla::Maybe<NonTrivialCopy>>);
constexpr auto constant = mozilla::Some(NonTrivialCopy{42});
static_assert(constant->value==42);
constexpr auto locale = js::LanguageId::fromValidBcp49("en-Latn-US");
static_assert(locale.language()=="en" && locale.script()=="Latn" && locale.region()=="US");
static_assert(js::LanguageId::und().language()=="und");
constexpr auto invalid = js::LanguageId::fromId(std::string_view{"EN_US"});
static_assert(!invalid);
constexpr auto remaining = js::LanguageId::fromBcp49("en-US-u-ca-gregory");
static_assert(remaining && remaining->second==12);
struct Tracked {
 int* alive;
 explicit Tracked(int* n):alive(n){++*alive;}
 Tracked(const Tracked& other):alive(other.alive){++*alive;}
 Tracked(Tracked&& other):alive(other.alive){++*alive;}
 ~Tracked(){--*alive;}
};
static void check(bool value){if(!value)std::abort();}
int main(){
 for(unsigned i=0;i<32;++i){
  int alive=0;
  {
   mozilla::Maybe<Tracked> value(std::in_place,&alive);check(alive==1);
   auto copy=value;check(alive==2);
   auto moved=std::move(value);check(!value && alive==2);
   copy.reset();check(alive==1);
   moved.reset();check(alive==0);
   value.emplace(&alive);check(alive==1);
  }
  check(alive==0);
  auto parsed=js::LanguageId::fromId(std::string_view{"zh_Hant_TW"});
  check(parsed && parsed->second==0 && parsed->first.region()=="TW");
 }
}
''')
            flags = ['-std=c++20', '-O1', '-DNDEBUG', '-DTRIMMED', '-D__ORBIS__',
                     '-I' + str(root / 'include'),
                     '-I' + str(ROOT / 'build/gecko-layout/dist/include'),
                     '-I' + str(SOURCE / 'js/src')]
            before = subprocess.run(DRIVER['compiler_command'](['--cxx', *flags, '-fsyntax-only', str(main)]),
                                    capture_output=True, text=True)
            self.assertNotEqual(before.returncode, 0)
            self.assertIn('not a literal type', before.stderr)
            PATCH['patch_maybe_constexpr'](root)
            result = subprocess.run(DRIVER['compiler_command'](['--cxx', *flags, '-fsyntax-only', str(main)]),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Native syntax check above uses SDK libc++/BSD headers. Runtime
            # lifetime checks below use the host C++ runtime, not firmware.
            exe = root / 'host'
            result = subprocess.run(['clang++', *flags, '-fsanitize=address,undefined',
                                     str(main), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
