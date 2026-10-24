# SPDX-License-Identifier: MPL-2.0
"""Failure-only generated Gecko instrumentation + real host POSIX operations."""
from pathlib import Path
import runpy
import subprocess
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-layout.py'))
NAME = 'ipc/glue/SharedMemoryPlatform_posix.cpp'
ORIGINAL = '''  if (mem == MAP_FAILED) {
    MOZ_LOG_FMT(gSharedMemoryLog, LogLevel::Warning, "call to mmap failed: {}",
                strerror(errno));
    return Nothing();
  }'''

class SharedMemoryDiagnosticsTest(unittest.TestCase):
    def test_generated_failure_block_preserves_errno_and_caps_enabled_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / NAME; source.parent.mkdir(parents=True)
            source.write_text(ORIGINAL)
            PATCH['patch_orbis_shared_memory_diagnostics'](root)
            first = source.read_bytes(), source.stat().st_mtime_ns
            PATCH['patch_orbis_shared_memory_diagnostics'](root)
            self.assertEqual(first, (source.read_bytes(), source.stat().st_mtime_ns))
            block = source.read_text()
            self.assertNotIn('mmap(', block)  # Never retries or changes the failed operation.
            self.assertNotIn('MAP_FIXED', block)
            harness = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cerrno>
#include <sys/stat.h>
#include <thread>
namespace mozilla { [[maybe_unused]] constexpr auto Relaxed=std::memory_order_relaxed;
template<class T, auto Order> struct Atomic:std::atomic<T> {
 using std::atomic<T>::atomic;
 bool compareExchange(T old,T value) {return this->compare_exchange_strong(old,value);}
}; }
std::atomic<unsigned> details{0}, stats{0};
bool enabled=false;
#define MAP_FAILED reinterpret_cast<void*>(intptr_t(-1))
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_SHARED 1
#define F_GETFL 3
#define _SC_PAGESIZE 30
#define MOZ_LOG_TEST(module, level) enabled
#define MOZ_LOG_FMT(module, level, ...) do { if (enabled) record(__VA_ARGS__); } while (false)
template<class... Args> void record(const char* format, Args...) {
 if (strstr(format,"Orbis shm mmap failure")) ++details;
 errno=777;
}
int fstat(int, struct stat* st) noexcept { ++stats; st->st_size=1234; errno=123; return 0; }
int fcntl(int, int) { errno=456; return 3; }
long sysconf(int) { errno=789; return 16384; }
bool Nothing() { return false; }
struct Handle { struct { int get() const { return 99; } } mHandle; };
bool failed_map() {
 void* mem=MAP_FAILED;
 [[maybe_unused]] Handle aHandle;
 [[maybe_unused]] void* aFixedAddress=nullptr;
 [[maybe_unused]] size_t aSize=16384;
 [[maybe_unused]] uint64_t aOffset=0;
 [[maybe_unused]] bool aReadOnly=true;
''' + block + r'''
 return true;
}
int main() {
 for(unsigned i=0;i<50;++i) { errno=22; assert(!failed_map()); }
 assert(stats==0 && details==0); // OFF means no added syscalls or records.
 enabled=true;
 std::thread workers[4];
 for(auto& t:workers) t=std::thread([] {
  for(unsigned i=0;i<64;++i) { errno=22; assert(!failed_map());
#ifdef __ORBIS__
   assert(errno==22);
#endif
  }
 });
 for(auto& t:workers)t.join();
#ifdef __ORBIS__
 assert(details==32 && stats==32);
#else
 assert(details==0 && stats==0);
#endif
}
'''
            cpp = root / 'failure.cpp'; cpp.write_text(harness)
            for defines in ([], ['-D__ORBIS__']):
                binary = root / ('failure-orbis' if defines else 'failure-other')
                subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                                '-pthread', *defines, str(cpp), '-o', str(binary)], check=True)
                subprocess.run([str(binary)], check=True)

    def test_real_posix_probe_with_sanitizers(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'probe'
            subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-I' + str(ROOT / 'include'), str(ROOT / 'tests/shared_memory_repro_main.cpp'),
                            '-o', str(binary)], check=True)
            for _ in range(2):
                output = subprocess.check_output([str(binary)], text=True)
                self.assertIn('PASS shm-repro', output)
                self.assertIn('cases=56', output)
                self.assertEqual(1, output.count('RESULT PASS'))
                self.assertIn('stage=page-offset', output)
                self.assertIn('stage=clone', output)

    def test_real_partial_failures_release_owned_descriptors_and_views(self):
        harness = r'''
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>
#include <cstdarg>
#include <cerrno>
#include <cassert>
int liveFiles=0, liveMaps=0, mapCalls=0, failMap=0;
bool failTruncate=false;
int injected_open(const char* name,int flags,mode_t mode) {
 int fd=::shm_open(name,flags,mode); if(fd>=0)++liveFiles; return fd;
}
int injected_close(int fd) { int rc=::close(fd); if(rc==0)--liveFiles; return rc; }
int injected_fcntl(int fd,int command,...) {
 if(command==F_DUPFD_CLOEXEC) {
  va_list args;va_start(args,command);int minimum=va_arg(args,int);va_end(args);
  int copy=::fcntl(fd,command,minimum);if(copy>=0)++liveFiles;return copy;
 }
 return ::fcntl(fd,command);
}
int injected_truncate(int fd,off_t size) {
 if(failTruncate){errno=ENOSPC;return -1;}return ::ftruncate(fd,size);
}
void* injected_map(void* addr,size_t size,int prot,int flags,int fd,off_t offset) {
 if(++mapCalls==failMap){errno=EINVAL;return MAP_FAILED;}
 void* p=::mmap(addr,size,prot,flags,fd,offset);if(p!=MAP_FAILED)++liveMaps;return p;
}
int injected_unmap(void* p,size_t size) {int rc=::munmap(p,size);if(rc==0)--liveMaps;return rc;}
#define shm_open injected_open
#define close injected_close
#define fcntl injected_fcntl
#define ftruncate injected_truncate
#define mmap injected_map
#define munmap injected_unmap
#include "orbisfox/shared_memory_repro.h"
int main() {
 FILE* out=tmpfile();assert(out);
 for(int step=1;step<=3;++step) {
  mapCalls=0;failMap=step;
  {orbisfox::shm_repro::Segment s;assert(!orbisfox::shm_repro::create(out,s,16384,100+step));}
  assert(liveFiles==0 && liveMaps==0);
 }
 failMap=0;failTruncate=true;
 {orbisfox::shm_repro::Segment s;assert(!orbisfox::shm_repro::create(out,s,16384,200));}
 assert(liveFiles==0 && liveMaps==0);fclose(out);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / 'failures.cpp'; cpp.write_text(harness)
            binary = cpp.with_suffix('')
            subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-I' + str(ROOT / 'include'), str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_sfo_verifier_checks_bounds_and_duplicate_keys(self):
        producer = runpy.run_path(str(ROOT / 'scripts/build-shared-memory-probe.py'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'param.sfo'
            keys, value = b'TITLE_ID\0', b'SHMP00001\0'
            for count in (1, 2):
                start = 20 + count * 16
                data = (struct.pack('<5I', 0x46535000, 0x101, start, start + len(keys), count) +
                        struct.pack('<HHIII', 0, 0x204, len(value), len(value), 0) * count + keys + value)
                path.write_bytes(data)
                if count == 1:
                    self.assertEqual({'TITLE_ID': (0x204, value)}, producer['read_sfo'](path))
                    bad = bytearray(data); struct.pack_into('<I', bad, 28, 1000000)
                    path.write_bytes(bad)
                    with self.assertRaises(ValueError): producer['read_sfo'](path)
                else:
                    with self.assertRaises(ValueError): producer['read_sfo'](path)

    def test_package_identity_does_not_replace_browser(self):
        producer = runpy.run_path(str(ROOT / 'scripts/build-shared-memory-probe.py'))
        self.assertEqual('SHMP00001', producer['TITLE'])
        self.assertRegex(producer['CONTENT'], r'^IV0000-SHMP00001_00-[A-Z0-9]{16}$')
        native = (ROOT / 'tests/shared_memory_repro_main.cpp').read_text()
        self.assertIn('/data/orbisfox-shmem-probe', native)
        self.assertNotIn('/data/orbisfox/', native)
        self.assertNotIn('diagnostics.enabled', native)
        self.assertIn('O_EXCL | O_NOFOLLOW', native)
        self.assertNotIn('MAP_FIXED', (ROOT / 'include/orbisfox/shared_memory_repro.h').read_text().split('namespace', 1)[1])

if __name__ == '__main__': unittest.main()
