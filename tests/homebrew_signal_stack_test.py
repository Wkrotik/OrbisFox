# SPDX-License-Identifier: MIT
"""BSD char* stack field: typed casts, unchanged mapping/fatal semantics."""
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
RELATIVE = 'third_party/abseil-cpp/absl/debugging/failure_signal_handler.cc'


class HomebrewSignalStackTest(unittest.TestCase):
    def fixture(self, root):
        original = subprocess.check_output(['git', '-C', str(SOURCE), 'show', PATCH['REVISION'] + ':' + RELATIVE], text=True)
        path = root / RELATIVE
        path.parent.mkdir(parents=True)
        path.write_text(original)
        return path

    def test_sdk_whole_unit_red_green_idempotency_and_atomic_drift(self):
        backend = ROOT / 'build/gecko-layout/third_party/abseil-cpp/absl/debugging/failure_signal_handler_gn/backend.mk'
        if not backend.is_file():
            self.skipTest('Requires configured native SDK engine and exported headers')
        flags = shlex.split(next(line.split(' += ', 1)[1] for line in backend.read_text().splitlines()
                                 if line.startswith('COMPUTED_CXXFLAGS += ')))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            original = path.read_text()
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_signal_stack'](root)
                    before = path.read_bytes(), path.stat().st_mtime_ns
                    PATCH['patch_native_signal_stack'](root)
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
                obj = root / 'signal.o'
                result = subprocess.run(DRIVER['compiler_command']([
                    '--cxx', '-std=gnu++20', *flags, '-c', str(path), '-o', str(obj)]), capture_output=True, text=True)
                if patched:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    symbols = subprocess.check_output(['llvm-nm', '-u', str(obj)], text=True)
                    self.assertIn(' U mmap\n', symbols)
                    self.assertIn(' U sigaltstack\n', symbols)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("incompatible type 'void *'", result.stderr)
            path.write_text(original.replace('  sigstk.ss_sp = malloc(sigstk.ss_size);', '  unknown_owned_edit();'))
            before = path.read_bytes(), path.stat().st_mtime_ns
            with self.assertRaisesRegex(RuntimeError, 'signal stack declaration drift'):
                PATCH['patch_native_signal_stack'](root)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_actual_stack_function_keeps_allocation_flags_and_fatal_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.fixture(root)
            PATCH['patch_native_signal_stack'](root)
            text = path.read_text()
            start = text.index('static bool SetupAlternateStackOnce() {')
            fragment = text[start:text.index('\n}\n', start) + 3]
            for mapped in (False, True):
                unit = root / 'fixture.cpp'
                unit.write_text('''#include <algorithm>
#include <cassert>
#include <cerrno>
#include <cstddef>
#include <cstring>
#include <sys/mman.h>
#include <unistd.h>
struct NativeStack {char* ss_sp; size_t ss_size; int ss_flags;};
struct Fatal {};
static int mode, allocations, installs, fatals, savedErrno;
alignas(16384) static char storage[65536*5];
static void* fake_mmap(void* address,size_t bytes,int prot,int flags,int fd,long offset){
 assert(!address && bytes==sizeof(storage) && prot==(PROT_READ|PROT_WRITE));
 assert(flags==(MAP_PRIVATE|MAP_ANONYMOUS|MAP_STACK) && fd==-1 && offset==0);
 ++allocations; if(mode==1){errno=ENOMEM;return MAP_FAILED;} return storage;
}
static void* fake_malloc(size_t bytes){
 assert(bytes==sizeof(storage));++allocations;
 if(mode==1){errno=ENOMEM;return nullptr;} return storage;
}
static long fake_sysconf(int){return 16384;}
static int fake_sigaltstack(const NativeStack* stack,NativeStack* previous){
 assert(stack && !previous && allocations==1 && stack->ss_sp==storage);
 assert(stack->ss_size==sizeof(storage) && stack->ss_flags==0);++installs;
 if(mode==2){errno=EACCES;return -1;} return 0;
}
#define stack_t NativeStack
#define SIGSTKSZ 8192
#define ABSL_HAVE_ADDRESS_SANITIZER 1
#define ABSL_RAW_LOG(severity,...) do{++fatals;savedErrno=errno;throw Fatal{};}while(0)
#define mmap fake_mmap
#define malloc fake_malloc
#define sigaltstack fake_sigaltstack
#define sysconf fake_sysconf
#undef __linux__
''' + ('#define ABSL_HAVE_MMAP 1\n' if mapped else '') + fragment + '''
int main(){
 for(int cycle=0;cycle<32;++cycle)for(mode=0;mode<3;++mode){
  allocations=installs=fatals=savedErrno=0;
  try{assert(SetupAlternateStackOnce());assert(mode==0 && fatals==0 && installs==1);}
  catch(Fatal){assert(mode!=0 && fatals==1 && installs==(mode==2));
   assert(savedErrno==(mode==1?ENOMEM:EACCES));}
  assert(allocations==1);
 }
}
''')
                exe = root / 'fixture'
                result = subprocess.run(['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                                         str(unit), '-o', str(exe)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
