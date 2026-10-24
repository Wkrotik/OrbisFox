# SPDX-License-Identifier: MIT
"""Native FILE ownership: no musl interposers, real buffered contention gate."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))


class HomebrewStdioTest(unittest.TestCase):
    def test_native_object_imports_real_stdio_and_defines_no_libc_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'stdio.o'
            args = ['--cxx', '-std=c++20', '-DORBISFOX_FULL_GECKO',
                    '-I' + str(ROOT / 'include'), '-c', str(ROOT / 'src/ps4/native_stdio.cpp'),
                    '-o', str(output)]
            result = subprocess.run(DRIVER['compiler_command'](args), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            symbols = subprocess.check_output(['llvm-nm', str(output)], text=True)
            for symbol in ('flockfile', 'ftrylockfile', 'funlockfile'):
                self.assertIn(' U ' + symbol + '\n', symbols)
                self.assertNotIn(' T ' + symbol + '\n', symbols)
            self.assertNotIn('__wrap_', symbols)
            self.assertNotIn('__lockfile', symbols)
            self.assertNotIn('native_stdio_entry_lock_count', symbols)
            runpy.run_path(str(ROOT / 'scripts/fetch-homebrew-service-headers.py'))['verify']()
            probe = Path(tmp) / 'probe.o'
            compiled = subprocess.run(DRIVER['compiler_command']([
                '--cxx', '-std=c++20', '-DORBISFOX_FULL_GECKO', '-I' + str(ROOT / 'include'),
                '-isystem', str(ROOT / '.deps/homebrew-service-headers/include'),
                '-c', str(ROOT / 'gecko/orbisfox/native/stdio_probe.cpp'), '-o', str(probe)]),
                capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            probe_symbols = subprocess.check_output(['llvm-nm', str(probe)], text=True)
            self.assertNotIn('native_stdio_entry_lock_count', probe_symbols)
            main = Path(tmp) / 'main.cpp'
            main.write_text('#include "orbisfox/native_stdio.h"\nint main(){return !orbisfox::initialize_native_stdio_locks();}\n')
            link = DRIVER['compiler_command'](['--cxx', '-std=c++20', '-I' + str(ROOT / 'include'),
                                               str(main), str(output), '-Wl,--no-gc-sections',
                                               '-o', str(Path(tmp) / 'stdio.elf')])
            result = subprocess.run(link, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            # Native ELF is a link gate only. Do not execute it on this host.

    def test_actual_probe_and_native_branch_under_host_sanitizers(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'orbis').mkdir()
            (folder / 'orbis/libkernel.h').write_text('extern "C" int scePthreadGetthreadid();\nextern "C" int sceKernelUsleep(unsigned);\n')
            main = folder / 'main.cpp'
            main.write_text('''#include "orbisfox/native_stdio.h"
#include "orbisfox/run_logs.h"
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <thread>
#include <csignal>
#include <unistd.h>
#include <sys/syscall.h>
static const char* directory;
static bool failJoin;
extern "C" int __real_pthread_join(pthread_t,void**);
extern "C" int __wrap_pthread_join(pthread_t thread,void** value){
 return failJoin ? EINVAL : __real_pthread_join(thread,value);
}
namespace orbisfox {
bool native_diagnostics_enabled(){return true;} // Fixture-owned temp file only.
bool copy_native_run_log_path(char* out,size_t capacity,const char* name){
 return make_run_log_path(out,capacity,directory,name);
}
void log(const char*,...){}
}
extern "C" int scePthreadGetthreadid(){return static_cast<int>(syscall(SYS_gettid));}
extern "C" int sceKernelUsleep(unsigned us){return usleep(us);}
int main(int argc,char** argv){
 assert(argc==2 || argc==3);directory=argv[1];
 if(argc==3){
  signal(SIGILL,[](int){_exit(73);});
  failJoin=true;
  (void)orbisfox::probe_native_stdio_locks();
  return 0; // A failed join must trap BEFORE returning/releasing the live state.
 }
 FILE* saved=stdout;stdout=nullptr;
 assert(!orbisfox::initialize_native_stdio_locks() && errno==EBADF);stdout=saved;
 for(unsigned i=0;i<32;++i){
  assert(orbisfox::initialize_native_stdio_locks());
  bool acquired=false;
  std::thread check([&]{acquired=ftrylockfile(stdout)==0;if(acquired)funlockfile(stdout);});
  check.join();assert(acquired); // No leaked recursive acquisition by the gate.
  assert(orbisfox::probe_native_stdio_locks()); // 4096 exact, unique rows, joined workers.
 }
}
''')
            command = ['clang++', '-std=c++20', '-O1', '-g', '-pthread', '-fsanitize=address,undefined',
                       '-DORBISFOX_FULL_GECKO', '-DORBISFOX_HOMEBREW_SDK', '-Wl,--wrap=pthread_join',
                       '-I' + str(folder), '-I' + str(ROOT / 'include'), str(main),
                       str(ROOT / 'src/ps4/native_stdio.cpp'),
                       str(ROOT / 'gecko/orbisfox/native/stdio_probe.cpp'), '-o', str(folder / 'test')]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(folder / 'test'), str(folder)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(folder / 'test'), str(folder), 'bad-join'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 73, result.stderr)


if __name__ == '__main__':
    unittest.main()
