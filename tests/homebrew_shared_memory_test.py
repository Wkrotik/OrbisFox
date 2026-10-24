# SPDX-License-Identifier: MIT
"""Pre-XPCOM logging ownership and genuine checked descriptor duplication."""
import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
UNIT = 'mfbt/UniquePtrExtensions.cpp'
REVISION = PATCH['REVISION']


class HomebrewSharedMemoryTest(unittest.TestCase):
    def fixture(self, root):
        unit = root / UNIT
        unit.parent.mkdir(parents=True)
        unit.write_bytes(subprocess.check_output([
            'git', '-C', str(SOURCE), 'show', REVISION + ':' + UNIT]))
        return unit

    def flags(self):
        return ['-std=c++20', '-DNDEBUG', '-DXP_UNIX=1',
                '-DMOZ_ORBIS_HOMEBREW_SDK=1', '-DIMPL_MFBT',
                '-I' + str(SOURCE / 'mfbt'),
                '-I' + str(ROOT / 'build/gecko-layout/dist/include')]

    def test_logging_owner_precedes_all_gecko_probes_and_outlives_bootstrap(self):
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        begin = main.index('ScopedLogging geckoLogging;')
        initialize = main.index('mozilla::LogModule::Init(7, argv);')
        self.assertLess(main.index('setenv("MOZ_LOG",'), begin)
        self.assertLess(begin, initialize)
        for operation in ('SetOrbisFoxHostCallbacks(', 'probe_gecko_shared_memory(',
                          'mozilla::GetBootstrap(', 'state.nativeUi.start('):
            self.assertLess(initialize, main.index(operation, main.index('int main(')))
        self.assertNotIn('NS_LogTerm(', main)
        self.assertIn('\n  ScopedLogging geckoLogging;\n', main)
        self.assertLess(begin, main.index('bootstrap.reset();'))
        # Verify the real RAII owner, not an invented logger-ready flag.
        header = (SOURCE / 'xpcom/build/nsXPCOM.h').read_text()
        self.assertIn('ScopedLogging() { NS_LogInit(); }', header)
        self.assertIn('~ScopedLogging() { NS_LogTerm(); }', header)
        logging = (SOURCE / 'xpcom/base/Logging.cpp').read_text()
        self.assertIn('void LogModule::Init(int argc, char* argv[])', logging)

    def test_producer_idempotence_drift_and_native_sdk_imports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unit = self.fixture(root)
            PATCH['patch_native_file_handle_clone'](root)
            before = unit.read_bytes(), unit.stat().st_mtime_ns
            PATCH['patch_native_file_handle_clone'](root)
            self.assertEqual((unit.read_bytes(), unit.stat().st_mtime_ns), before)
            output = root / 'native.o'
            subprocess.run(DRIVER['compiler_command']([
                '--cxx', *self.flags(), '-c', str(unit), '-o', str(output)]), check=True,
                capture_output=True, text=True)
            symbols = subprocess.check_output(['llvm-nm', '-u', str(output)], text=True)
            for name in ('dup', 'fcntl', 'close', '__error'):
                self.assertIn(' U ' + name + '\n', symbols)
            for name in ('dup', 'fcntl', 'close'):
                self.assertNotIn(' T ' + name + '\n', symbols)
            unit.write_text(unit.read_text().replace('fd = fcntl(aFile, F_DUPFD_CLOEXEC, 0);',
                                                    'fd = unknown_clone(aFile);'))
            changed = unit.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'clone declaration drift'):
                PATCH['patch_native_file_handle_clone'](root)
            self.assertEqual(unit.read_bytes(), changed)

    def test_actual_platform_clone_keeps_errno_across_lazy_logging(self):
        relative = 'ipc/glue/SharedMemoryPlatform_posix.cpp'
        original = subprocess.check_output([
            'git', '-C', str(SOURCE), 'show', REVISION + ':' + relative]).decode()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unit = root / relative
            unit.parent.mkdir(parents=True)
            unit.write_text(original)
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_shared_memory_errors'](root)
                    before = unit.read_bytes(), unit.stat().st_mtime_ns
                    PATCH['patch_native_shared_memory_errors'](root)
                    self.assertEqual((unit.read_bytes(), unit.stat().st_mtime_ns), before)
                text = unit.read_text()
                body = text[text.index('PlatformHandle Platform::CloneHandle('):
                            text.index('bool Platform::Freeze(')]
                test = root / 'logging.cpp'
                test.write_text(r'''
#include <assert.h>
#include <errno.h>
static bool enabled;
static int described;
struct PlatformHandle {bool valid; explicit operator bool() const {return valid;}};
PlatformHandle DuplicateFileHandle(const PlatformHandle&) {errno=EMFILE;return {false};}
struct Platform {static PlatformHandle CloneHandle(const PlatformHandle&);};
const char* described_error(int error) {described=error;return "failure";}
#define strerror described_error
// Lazy module lookup/initialization and log I/O can each change errno, even
// when a disabled level never evaluates the formatted message itself.
#define MOZ_LOG_FMT(module,level,pattern,message) do { \
  errno=EAGAIN; if(enabled)(void)(message); errno=EBUSY; \
} while(0)
''' + body + r'''
int main() {
 for(int i=0;i<32;++i)for(int level=0;level<2;++level) {
  enabled=level;described=0;errno=0;
  assert(!Platform::CloneHandle({true}));
  assert(errno==EMFILE);
  assert(described==(enabled?EMFILE:0));
 }
}
''')
                output = root / 'logging'
                subprocess.run(['clang++', '-std=c++20', '-fsanitize=address,undefined',
                                str(test), '-o', str(output)], check=True,
                               capture_output=True, text=True)
                result = subprocess.run([str(output)], capture_output=True, text=True, check=False)
                if patched:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('errno==EMFILE', result.stderr)
            unit.write_text(unit.read_text().replace('const int error = errno;',
                                                    'const int error = unknown_errno;'))
            changed = unit.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'error-path drift'):
                PATCH['patch_native_shared_memory_errors'](root)
            self.assertEqual(unit.read_bytes(), changed)

    def test_failure_diagnostics_preserve_fd_ownership_and_off_state(self):
        text = (ROOT / 'gecko/orbisfox/native/shared_memory_probe.cpp').read_text()
        helpers = text[text.index('namespace {'):text.index('bool probe_gecko_shared_memory()')]
        prefix = r'''
#include "mozilla/ScopeExit.h"
#include "mozilla/UniquePtrExtensions.h"
#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>
namespace mozilla::ipc::shared_memory {
struct ReadOnlyHandle {
 mozilla::UniqueFileHandle fd;
 size_t Size() const {return 16384;}
 mozilla::UniqueFileHandle TakePlatformHandle() && {return std::move(fd);}
};
}
namespace orbisfox {
static bool enabled;
static int queries;
static std::string messages;
bool native_diagnostics_enabled(){return enabled;}
int32_t sceKernelAvailableFlexibleMemorySize(size_t address) {
 ++queries;*reinterpret_cast<size_t*>(address)=123456;return 0;
}
void log(const char* pattern, ...) {
 char buffer[2048];va_list args;va_start(args,pattern);
 vsnprintf(buffer,sizeof(buffer),pattern,args);va_end(args);
 messages+=buffer;messages+='\n';
}
'''
        suffix = r'''
int count_fds() {
 int count=0;DIR* directory=opendir("/proc/self/fd");assert(directory);
 while(readdir(directory))++count;
 assert(closedir(directory)==0);return count;
}
void run() {
 for(int i=0;i<32;++i)for(int capture=0;capture<2;++capture)for(int zero=0;zero<2;++zero) {
  const int before=count_fds();
  {
   char path[]="/tmp/orbis-readonly-XXXXXX";
   int writer=mkstemp(path);assert(writer>=0);assert(ftruncate(writer,16384)==0);
   int original=open(path,O_RDONLY);assert(original>=0);assert(unlink(path)==0);
   assert(close(writer)==0);int cloned=dup(original);assert(cloned>=0);
   mozilla::ipc::shared_memory::ReadOnlyHandle source{mozilla::UniqueFileHandle{original}};
   mozilla::ipc::shared_memory::ReadOnlyHandle copy{mozilla::UniqueFileHandle{cloned}};
   int savedInput=-1;
   if(zero){savedInput=dup(0);assert(savedInput>=0);assert(close(0)==0);}
   enabled=capture;queries=0;messages.clear();
   diagnose_readonly_failure(source,copy);
   if(capture) {
    assert(queries==1);
    assert(!source.fd && !copy.fd);
    assert(fcntl(original,F_GETFD)==-1 && errno==EBADF);
    assert(fcntl(cloned,F_GETFD)==-1 && errno==EBADF);
    assert(messages.find("role=frozen")!=std::string::npos);
    assert(messages.find("role=clone")!=std::string::npos);
    assert(messages.find("role=plain-dup")!=std::string::npos);
    assert(messages.find("failed=0 errno=0")!=std::string::npos);
    assert(messages.find("unmap: result=0 errno=0")!=std::string::npos);
    if(zero)assert(messages.find("role=plain-dup fd=0 ")!=std::string::npos);
   } else {
    assert(queries==0 && messages.empty());
    assert(source.fd && copy.fd);
    assert(fcntl(original,F_GETFD)>=0 && fcntl(cloned,F_GETFD)>=0);
   }
   if(zero) {
    assert(fcntl(0,F_GETFD)==-1 && errno==EBADF);
    assert(dup2(savedInput,0)==0);assert(close(savedInput)==0);
   }
  }
  assert(count_fds()==before);
 }
}
}
int main(){orbisfox::run();}
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unit = root / 'diagnostics.cpp'
            unit.write_text(prefix + helpers + suffix)
            output = root / 'diagnostics'
            subprocess.run(['clang++', '-std=c++20', '-UXP_WIN', '-DXP_UNIX=1',
                            '-fsanitize=address,undefined',
                            '-I' + str(ROOT / 'build/gecko-layout/dist/include'),
                            '-I' + str(SOURCE / 'mfbt'), str(unit), str(SOURCE / UNIT),
                            '-o', str(output)], check=True, capture_output=True, text=True)
            subprocess.run([str(output)], check=True, capture_output=True, text=True)

    def test_probe_captures_each_operation_errno_and_keeps_failure(self):
        source = (ROOT / 'gecko/orbisfox/native/shared_memory_probe.cpp').read_text()
        body = source[source.index('bool probe_gecko_shared_memory()'):source.rindex('\n}')]
        prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string>
#include <utility>
namespace mozilla::ipc::shared_memory {
inline unsigned char data[524288];
inline int mode;
struct Handle;
struct Mapping {
 size_t bytes; bool valid;
 explicit operator bool() const {return valid;}
 size_t Size() const {return valid?bytes:0;}
 template<class T> T* DataAs() const {return reinterpret_cast<T*>(data);}
 Handle Freeze();
};
struct Handle {
 size_t bytes;bool cloned;
 explicit operator bool() const {return true;}
 size_t Size() const {return bytes;}
 Handle Clone() const {errno=EINVAL;return {bytes,true};}
 Mapping Map() const {
  assert(errno == 0);
  if(cloned && mode) {if(mode==2)errno=ENOMEM;return {bytes,false};}
  return {bytes,true};
 }
};
Handle Mapping::Freeze(){return {bytes,false};}
struct Freezable {
 size_t bytes;
 explicit operator bool() const {return true;}
 Mapping Map() const {return {bytes,true};}
};
Freezable CreateFreezable(size_t bytes){return {bytes};}
}
namespace orbisfox {
using mozilla::ipc::shared_memory::Handle;
static std::string messages;
static bool diagnostics;
static int observations;
void log(const char* pattern, ...) {
 char buffer[1024];va_list args;va_start(args,pattern);
 vsnprintf(buffer,sizeof(buffer),pattern,args);va_end(args);
 messages+=buffer;messages+='\n';
}
void log_pool(const char*) {if(diagnostics)errno=EAGAIN;}
void diagnose_readonly_failure(Handle&, Handle&) {
 if(diagnostics){++observations;errno=EIO;}
}
'''
        suffix = r'''
}
int main() {
 using namespace orbisfox;
 for(int i=0;i<32;++i)for(int capture=0;capture<2;++capture)for(int mode=0;mode<3;++mode) {
  diagnostics=capture;observations=0;messages.clear();errno=0;
  mozilla::ipc::shared_memory::mode=mode;
  assert(probe_gecko_shared_memory()==(mode==0));
  assert(messages.find("source-bytes=16384 clone-bytes=16384")!=std::string::npos);
  const char* expected=mode==2?"source_errno=0 clone_errno=12":"source_errno=0 clone_errno=0";
  assert(messages.find(expected)!=std::string::npos);
  if(mode) {assert(errno==(mode==2?ENOMEM:0));assert(observations==capture);}
 }
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for patched in (False, True):
                selected = body if patched else body.replace(
                    '        errno = 0;\n        auto readonly = frozen.Map();',
                    '        auto readonly = frozen.Map();')
                test = root / 'probe.cpp'
                test.write_text(prefix + selected + suffix)
                output = root / 'probe'
                subprocess.run(['clang++', '-std=c++20', '-fsanitize=address,undefined',
                                str(test), '-o', str(output)], check=True,
                               capture_output=True, text=True)
                result = subprocess.run([str(output)], capture_output=True, text=True,
                                        check=False)
                if patched:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('errno == 0', result.stderr)
        main = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
        self.assertIn('!native_diagnostics_enabled() ? ""', main)
        self.assertIn('timestamp,SharedMemory:2,nsHostResolver:3', main)

    def test_actual_clone_fallback_errors_cloexec_readonly_and_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unit = self.fixture(root)
            main = root / 'test.cpp'
            main.write_text(r'''
#include "UniquePtrExtensions.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdlib.h>
#include <unistd.h>
using mozilla::DuplicateFileHandle;
static int mode, clones, duplicates, closes;
static int cloned = -1;
extern "C" int __real_fcntl(int,int,...);
extern "C" int __real_dup(int);
extern "C" int __real_close(int);
extern "C" int __wrap_fcntl(int fd,int command,...) {
  va_list args; va_start(args,command);
  int value = command == F_GETFD ? 0 : va_arg(args,int);
  va_end(args);
  if (command == F_DUPFD_CLOEXEC) {
    ++clones;
    errno=0;return 0; // Observed firmware behavior: success-shaped non-duplicate.
  }
  if (fd == cloned && command == F_GETFD && mode == 4) {errno=EIO;return -1;}
  if (fd == cloned && command == F_SETFD && mode == 5) {errno=EPERM;return -1;}
  return __real_fcntl(fd,command,value);
}
extern "C" int __wrap_dup(int fd) {
  ++duplicates;
  if (mode==2 || mode==3 || mode==6 || mode==7) {
    errno=mode==2?EMFILE:mode==3?ENFILE:EINTR;return -1;
  }
  return cloned=__real_dup(fd);
}
extern "C" int __wrap_close(int fd) {
  if(fd==cloned)++closes;
  int result=__real_close(fd);
  if(fd==cloned)errno=EBUSY; // Cleanup must not erase the operation's failure.
  return result;
}
int main() {
 for(int iteration=0;iteration<32;++iteration) {
  char path[]="/tmp/orbisfox-clone-XXXXXX";
  int writefd=mkstemp(path);assert(writefd>=0);
  assert(write(writefd,"immutable",9)==9);
  int fd=open(path,O_RDONLY|O_CLOEXEC);assert(fd>=0);
  unlink(path);__real_close(writefd);
  for(mode=0;mode<=7;++mode) {
   clones=duplicates=closes=0;cloned=-1;errno=0;
   auto copy=DuplicateFileHandle(fd);
   int error=errno;
   assert(clones==0);
   if(mode<=1) {
    assert(copy && int(copy.get())!=fd);
    assert(duplicates==1);
    assert((__real_fcntl(copy.get(),F_GETFD)&FD_CLOEXEC)!=0);
    assert((__real_fcntl(copy.get(),F_GETFL)&O_ACCMODE)==O_RDONLY);
    char text[10]={};assert(pread(copy.get(),text,9,0)==9);
    assert(text[0]=='i' && text[8]=='e');
    assert(write(copy.get(),"x",1)==-1 && errno==EBADF);
   } else {
    assert(!copy);
    assert(error==(mode==2?EMFILE:mode==3?ENFILE:mode==4?EIO:mode==5?EPERM:EINTR));
    assert(duplicates==1);
    assert(closes==(mode==4 || mode==5));
    if(mode==4 || mode==5)assert(__real_fcntl(cloned,F_GETFD)==-1 && errno==EBADF);
   }
   assert(__real_fcntl(fd,F_GETFD)>=0);
  }
  clones=duplicates=0;assert(!DuplicateFileHandle(-1));assert(!clones && !duplicates);
  __real_close(fd);
 }
}
''')
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_file_handle_clone'](root)
                # Keep fixture assertions enabled; NDEBUG is only for production's
                # optional Gecko debug diagnostics, which are unrelated to failure handling.
                obj = root / 'unit.o'
                subprocess.run(['clang++', *self.flags(), '-fsanitize=address,undefined',
                                '-c', str(unit), '-o', str(obj)], check=True,
                               capture_output=True, text=True)
                binary = root / 'test'
                subprocess.run(['clang++', *[x for x in self.flags() if x != '-DNDEBUG'],
                                '-fsanitize=address,undefined', str(main), str(obj),
                                '-Wl,--wrap=fcntl,--wrap=dup,--wrap=close', '-o', str(binary)],
                               check=True, capture_output=True, text=True)
                result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
                if patched:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('clones==0', result.stderr)


if __name__ == '__main__':
    unittest.main()
