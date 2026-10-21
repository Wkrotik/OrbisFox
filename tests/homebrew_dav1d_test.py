# SPDX-License-Identifier: MIT
"""Use dav1d's genuine POSIX allocation branch, not BSD's error malloc.h."""
from pathlib import Path
import runpy
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
RELATIVE = 'third_party/dav1d/src/mem.h'


class HomebrewDav1dTest(unittest.TestCase):
    def fixture(self, root):
        original = subprocess.check_output(['git', '-C', str(SOURCE), 'show',
                                           PATCH['REVISION'] + ':' + RELATIVE], text=True)
        path = root / RELATIVE
        path.parent.mkdir(parents=True)
        path.write_text(original)
        return path

    def test_actual_sdk_cdf_unit_header_red_green_and_idempotency(self):
        backend = ROOT / 'build/gecko-layout/media/libdav1d/backend.mk'
        if not backend.is_file():
            self.skipTest('Requires native configured Gecko backend and exported headers')
        flags = shlex.split(next(line.split(' += ', 1)[1] for line in backend.read_text().splitlines()
                                 if line.startswith('COMPUTED_CFLAGS += ')))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            cdf = path.parent / 'cdf.c'
            cdf.write_bytes((SOURCE / 'third_party/dav1d/src/cdf.c').read_bytes())
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_dav1d_headers'](root)
                    before = path.read_bytes(), path.stat().st_mtime_ns
                    PATCH['patch_native_dav1d_headers'](root)
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
                result = subprocess.run(DRIVER['compiler_command']([
                    '-I' + str(root / 'third_party/dav1d'), *flags, '-c', str(cdf),
                    '-o', str(root / 'cdf.o')]), capture_output=True, text=True)
                if patched:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('<malloc.h> has been replaced by <stdlib.h>', result.stderr)
            path.write_text(path.read_text().replace('#include <malloc.h>', '#include <unknown_owned_header.h>'))
            before = path.read_bytes(), path.stat().st_mtime_ns
            with self.assertRaisesRegex(RuntimeError, 'dav1d allocator header drift'):
                PATCH['patch_native_dav1d_headers'](root)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_original_allocation_function_posix_imports_alignment_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            PATCH['patch_native_dav1d_headers'](root)
            text = path.read_text()
            allocation = text.split('static inline void *dav1d_alloc_aligned_internal', 1)[1]
            allocation = 'static inline void *dav1d_alloc_aligned_internal' + allocation.split('#if TRACK_HEAP_ALLOCATIONS', 1)[0]
            header = root / 'allocation.h'
            header.write_text('#include <stdlib.h>\n#include <assert.h>\n' + allocation)
            unit = root / 'native.c'
            unit.write_text('#define HAVE_POSIX_MEMALIGN 1\n#define HAVE_MEMALIGN 1\n'
                            '#include "allocation.h"\n'
                            'void *dav1d_native_alloc(size_t size,size_t align) {return dav1d_alloc_aligned_internal(size,align);}\n')
            output = root / 'allocation.o'
            result = subprocess.run(DRIVER['compiler_command']([
                '-c', str(unit), '-o', str(output)]), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', '-u', str(output)], text=True)
            self.assertIn(' U posix_memalign\n', symbols)
            self.assertNotIn(' U memalign\n', symbols)
            host = root / 'host.c'
            host.write_text('''#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
static int forced,calls;
static int checked_posix(void **p,size_t a,size_t s) {
 ++calls; assert(a==64 && s==333); if(forced)return forced;
 return posix_memalign(p,a,s);
}
#define HAVE_POSIX_MEMALIGN 1
#define HAVE_MEMALIGN 1
#define posix_memalign checked_posix
#include "allocation.h"
int main(void) {
 for(int i=0;i<32;++i) {
  forced=0; calls=0;
  void *p=dav1d_alloc_aligned_internal(333,64);
  assert(p && calls==1 && (((uintptr_t)p)&63)==0); free(p);
  forced=ENOMEM; assert(dav1d_alloc_aligned_internal(333,64)==NULL);
  forced=EINVAL; assert(dav1d_alloc_aligned_internal(333,64)==NULL);
 }
}
''')
            exe = root / 'host'
            result = subprocess.run(['clang', '-O1', '-g', '-fsanitize=address,undefined',
                                     str(host), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
