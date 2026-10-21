# SPDX-License-Identifier: MIT
"""Pinned Gecko allocation declarations/fallbacks; the SDK stays the owner."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))


class HomebrewAllocatorTest(unittest.TestCase):
    def original(self, relative='memory/build/Fallback.cpp'):
        return subprocess.check_output(['git', '-C', str(ROOT / '.deps/gecko-layout'),
                                       'show', PATCH['REVISION'] + ':' + relative], text=True)

    def consumer(self, source):
        path = source / 'memory/mozalloc/mozalloc.cpp'
        path.parent.mkdir(parents=True)
        path.write_text(self.original('memory/mozalloc/mozalloc.cpp'))
        return path

    def test_pinned_fallback_idempotency_and_drift_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            path = source / 'memory/build/Fallback.cpp'
            path.parent.mkdir(parents=True)
            original = self.original()
            path.write_text(original)
            consumer = self.consumer(source)
            PATCH['patch_allocator_fallback'](source)
            before = path.read_bytes(), path.stat().st_mtime_ns
            PATCH['patch_allocator_fallback'](source)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            edited = original.replace('    return nullptr;', '    return arbitrary_unknown_edit;')
            path.write_text(edited)
            with self.assertRaisesRegex(RuntimeError, 'allocator fallback drift'):
                PATCH['patch_allocator_fallback'](source)
            self.assertEqual(path.read_text(), edited)
            path.write_text(original)
            consumer.write_text('unknown declaration edit')
            with self.assertRaisesRegex(RuntimeError, 'declaration drift'):
                PATCH['patch_allocator_fallback'](source)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(consumer.read_text(), 'unknown declaration edit')

    def test_actual_native_headers_need_consumer_declaration_even_when_symbol_links(self):
        driver = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            fallback = source / 'memory/build/Fallback.cpp'
            fallback.parent.mkdir(parents=True)
            fallback.write_text(self.original())
            consumer = self.consumer(source)
            for expected in (False, True):
                if expected:
                    PATCH['patch_allocator_fallback'](source)
                declaration = consumer.read_text().split('#ifndef __wasm__', 1)[1].split('void* moz_xmemalign', 1)[0]
                probe = source / 'consumer.cpp'
                probe.write_text('#include <stdlib.h>\n' + declaration + '\nvoid* use(size_t a,size_t n){return memalign(a,n);}\n')
                command = driver['compiler_command']([
                    '--cxx', '-std=c++20', '-DHAVE_MEMALIGN=1', '-DMOZ_ORBIS_HOMEBREW_SDK=1',
                    '-c', str(probe), '-o', str(source / 'consumer.o')])
                result = subprocess.run(command, capture_output=True, text=True)
                if expected:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    (source / 'mozmemory.h').write_text('#define MOZ_MEMORY_API extern "C"\n')
                    (source / 'mozjemalloc.h').write_text('')
                    prefix = fallback.read_text().split('struct SystemMalloc {', 1)[0]
                    probe.write_text('#include <stdlib.h>\n' + prefix + '\nvoid* use(size_t a,size_t n){return memalign(a,n);}\n')
                    compiled = subprocess.run(driver['compiler_command']([
                        '--cxx', '-std=c++20', '-DHAVE_MEMALIGN=1', '-DMOZ_ORBIS_HOMEBREW_SDK=1',
                        '-I' + str(source),
                        '-c', str(probe), '-o', str(source / 'fallback.o')]),
                        capture_output=True, text=True)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    symbols = subprocess.check_output(['llvm-nm', str(source / 'fallback.o')], text=True)
                    self.assertIn(' U memalign\n', symbols)
                    self.assertNotIn(' T memalign\n', symbols)
                    self.assertNotIn('posix_memalign', symbols)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("undeclared identifier 'memalign'", result.stderr)

    def test_missing_symbol_posix_fallback_propagates_errors_without_replacing_heap(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            path = source / 'memory/build/Fallback.cpp'
            path.parent.mkdir(parents=True)
            path.write_text(self.original())
            self.consumer(source)
            (source / 'mozmemory.h').write_text('#define MOZ_MEMORY_API extern "C"\n')
            (source / 'mozjemalloc.h').write_text('')
            # Exercise the exact production fallback definition, excluding the
            # unrelated DummyArenaAllocator template/Gecko header graph.
            main = source / 'test.cpp'
            main.write_text('''#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
static int calls, forced;
static int test_posix_memalign(void** p, size_t align, size_t size) {
 ++calls; if(forced) return forced; return ::posix_memalign(p, align, size);
}
// Model an actually missing symbol, not the native SDK's available export.
#define MOZ_ORBIS_HOMEBREW_SDK 1
#define memalign orbis_test_memalign
#define posix_memalign test_posix_memalign
#include "fallback-function.cpp"
#undef memalign
#undef posix_memalign
int main() {
 for(int i=0;i<32;++i) {
  forced=0; calls=0;
  void* p=orbis_test_memalign(64,137);
  assert(calls==1 && p && (reinterpret_cast<uintptr_t>(p)&63)==0);
  free(p);
  forced=EINVAL; errno=0;
  assert(!orbis_test_memalign(3,137) && errno==EINVAL);
  forced=ENOMEM; errno=0;
  assert(!orbis_test_memalign(64,137) && errno==ENOMEM);
  forced=EINVAL; errno=0;
  assert(!orbis_test_memalign(64,137) && errno==EINVAL);
 }
}
''')
            for expected in (False, True):
                if expected:
                    PATCH['patch_allocator_fallback'](source)
                (source / 'fallback-function.cpp').write_text(path.read_text().split('struct SystemMalloc {', 1)[0])
                command = ['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                           '-I' + str(source), str(main), '-o', str(source / 'test')]
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                executed = subprocess.run([str(source / 'test')], capture_output=True, text=True)
                if expected:
                    self.assertEqual(executed.returncode, 0, executed.stderr)
                else:
                    self.assertNotEqual(executed.returncode, 0)
                    self.assertIn('errno==EINVAL', executed.stderr)


if __name__ == '__main__':
    unittest.main()
