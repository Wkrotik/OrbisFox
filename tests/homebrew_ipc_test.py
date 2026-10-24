# SPDX-License-Identifier: MIT
"""SDK-native process-name declaration and unchanged checked pipe primitives."""
from pathlib import Path
import runpy
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / '.deps/gecko-layout'
PATCH = runpy.run_path(str(ROOT / 'scripts/patch-gecko-layout.py'))
DRIVER = runpy.run_path(str(ROOT / 'scripts/homebrew-cc.py'))
REVISION = runpy.run_path(str(ROOT / 'scripts/configure-gecko-layout.py'))['REVISION']
WATCHER = 'ipc/chromium/src/chrome/common/process_watcher_posix_sigchld.cc'
NAME = 'ipc/glue/ProcessUtils_bsd.cpp'


class HomebrewIpcTest(unittest.TestCase):
    def fixture(self, root):
        for name in (WATCHER, NAME):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(subprocess.check_output(['git', '-C', str(SOURCE),
                                                      'show', REVISION + ':' + name]))

    def test_actual_sdk_name_primitive_and_pipe_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / NAME).write_text((root / NAME).read_text().replace(
                '#if !defined(XP_NETBSD)', '#if !defined(XP_NETBSD) && !defined(__ORBIS__)'))
            # Isolate the production naming function from unrelated Gecko headers.
            (root / 'ProcessUtils.h').write_text('')
            for patched in (False, True):
                if patched:
                    PATCH['patch_native_ipc_primitives'](root)
                    before = {name: ((root / name).read_bytes(), (root / name).stat().st_mtime_ns)
                              for name in (WATCHER, NAME)}
                    PATCH['patch_native_ipc_primitives'](root)
                    for name, value in before.items():
                        self.assertEqual(((root / name).read_bytes(), (root / name).stat().st_mtime_ns), value)
                name = root / 'name.cpp'
                name.write_text((root / NAME).read_text())
                result = subprocess.run(DRIVER['compiler_command']([
                    '--cxx', '-std=c++20', '-D__ORBIS__', '-c', str(name), '-o', str(root / 'name.o')]),
                    capture_output=True, text=True)
                if not patched:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("undeclared identifier 'pthread_set_name_np'", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    symbols = subprocess.check_output(['llvm-nm', str(root / 'name.o')], text=True)
                    self.assertIn(' U pthread_set_name_np\n', symbols)
                    self.assertIn(' U pthread_self\n', symbols)
                pipe = root / 'pipe.cpp'
                pipe.write_text(self.pipe_fragment((root / WATCHER).read_text()))
                result = subprocess.run(DRIVER['compiler_command']([
                    '--cxx', '-std=c++20', '-c', str(pipe), '-o', str(root / 'pipe.o')]),
                    capture_output=True, text=True)
                if not patched:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("undeclared identifier 'pipe2'", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    symbols = subprocess.check_output(['llvm-nm', str(root / 'pipe.o')], text=True)
                    self.assertIn(' U pipe\n', symbols)
                    self.assertIn(' U fcntl\n', symbols)
                    self.assertNotIn(' U pipe2\n', symbols)
            main = root / 'main.cpp'
            main.write_text('''namespace mozilla {namespace ipc {void SetThisProcessName(const char*);}}
void fixture_pipe_init();
int main(){mozilla::ipc::SetThisProcessName("probe");fixture_pipe_init();return 0;}
''')
            result = subprocess.run(DRIVER['compiler_command']([
                '--cxx', str(main), str(root / 'name.o'), str(root / 'pipe.o'), '-Wl,--no-gc-sections',
                '-o', str(root / 'native.elf')]), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_actual_spidermonkey_thread_unit_native_declaration_red_green(self):
        helper = runpy.run_path(str(ROOT / 'scripts/patch-gecko-homebrew.py'))
        backend = ROOT / 'build/gecko-layout/js/src/threading/backend.mk'
        if not backend.is_file():
            self.skipTest('Requires configured native SDK Gecko backend and exported headers')
        flags = shlex.split(next(line.split(' += ', 1)[1] for line in backend.read_text().splitlines()
                                 if line.startswith('COMPUTED_CXXFLAGS += ')))
        relative = 'js/src/threading/posix/PosixThread.cpp'
        original = subprocess.check_output(['git', '-C', str(SOURCE), 'show', REVISION + ':' + relative], text=True)
        # The legacy canonical patch intentionally keeps optional name retrieval
        # disabled; reproduce that known prerequisite, not a new SDK shim.
        original = original.replace('#ifdef HAVE_PTHREAD_GETNAME_NP',
                                    '#if defined(HAVE_PTHREAD_GETNAME_NP) && !defined(__ORBIS__)')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unit = root / relative
            unit.parent.mkdir(parents=True)
            unit.write_text(original)
            for patched in (False, True):
                if patched:
                    helper['patch_native_js_thread'](root)
                    before = unit.read_bytes(), unit.stat().st_mtime_ns
                    helper['patch_native_js_thread'](root)
                    self.assertEqual((unit.read_bytes(), unit.stat().st_mtime_ns), before)
                output = root / 'thread.o'
                result = subprocess.run(DRIVER['compiler_command']([
                    '--cxx', '-std=gnu++20', *flags, '-c', str(unit), '-o', str(output)]),
                    capture_output=True, text=True)
                if not patched:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("undeclared identifier 'pthread_set_name_np'", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    symbols = subprocess.check_output(['llvm-nm', '-u', str(output)], text=True)
                    self.assertIn(' U pthread_set_name_np\n', symbols)
                    self.assertIn(' U pthread_self\n', symbols)
            unknown_edits = (original.replace('#include "mozilla/Assertions.h"', '#include "unexpected-edit.h"'),
                             unit.read_text().replace('<pthread_np.h>', '<unknown-owned-edit.h>'))
            for edited in unknown_edits:
                unit.write_text(edited)
                before = unit.read_bytes(), unit.stat().st_mtime_ns
                with self.assertRaisesRegex(RuntimeError, 'thread declaration drift'):
                    helper['patch_native_js_thread'](root)
                self.assertEqual((unit.read_bytes(), unit.stat().st_mtime_ns), before)

    def test_actual_angle_thread_unit_native_declaration_red_green(self):
        backend = ROOT / 'build/gecko-layout/third_party/angle/angle_common_gn/backend.mk'
        if not backend.is_file():
            self.skipTest('Requires configured native SDK Gecko backend and exported headers')
        flags = shlex.split(next(line.split(' += ', 1)[1] for line in backend.read_text().splitlines()
                                 if line.startswith('COMPUTED_CXXFLAGS += ')))
        canonical = (ROOT / 'gecko/third_party/angle/src/common/system_utils_orbis.cpp').read_text()
        declaration = '#ifdef ORBISFOX_HOMEBREW_SDK\n#include <pthread_np.h>\n#endif\n'
        self.assertEqual(canonical.count(declaration), 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unit = root / 'system_utils_orbis.cpp'
            for patched in (False, True):
                unit.write_text(canonical if patched else canonical.replace(declaration, ''))
                output = root / 'angle.o'
                result = subprocess.run(DRIVER['compiler_command']([
                    '--cxx', '-std=gnu++20', *flags,
                    '-I' + str(SOURCE / 'third_party/angle/src/common'),
                    '-c', str(unit), '-o', str(output)]), capture_output=True, text=True)
                if not patched:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("undeclared identifier 'pthread_set_name_np'", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    symbols = subprocess.check_output(['llvm-nm', '-u', str(output)], text=True)
                    self.assertIn(' U pthread_set_name_np\n', symbols)
                    self.assertIn(' U pthread_self\n', symbols)
                    self.assertIn(' U clock_gettime\n', symbols)

    def pipe_fragment(self, text):
        feature = text[text.index('#if !defined(XP_DARWIN)'):text.index('// The basic idea here')]
        start = text.index('static void ProcessWatcherInit() {')
        body = text[start:text.index('  // Currently there are no other SIGCHLD handlers', start)]
        # Preserve actual API calls, checked failures and feature branches. Only
        # replace the unavailable Chromium log class; failed checks still trap.
        return '''#include <fcntl.h>
#include <unistd.h>
struct FixtureLog {
 explicit FixtureLog(bool good) {if(!good)__builtin_trap();}
 FixtureLog& operator<<(const char*) {return *this;}
};
#define CHECK(value) FixtureLog(!!(value))
static int gSignalPipe[2];
''' + feature + body + '\n}\nvoid fixture_pipe_init(){ProcessWatcherInit();}\n'

    def test_checked_upstream_pipe_fallback_host_flags_and_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            PATCH['patch_native_ipc_primitives'](root)
            source = root / 'host.cpp'
            source.write_text(self.pipe_fragment((root / WATCHER).read_text()) + '''
#include <cassert>
#include <cerrno>
int main(){
 for(int i=0;i<32;++i){
  fixture_pipe_init();
  for(int fd:gSignalPipe){
   assert((fcntl(fd,F_GETFL)&O_NONBLOCK)!=0);
   assert((fcntl(fd,F_GETFD)&FD_CLOEXEC)!=0);
  }
  char c=0;errno=0;
  assert(read(gSignalPipe[0],&c,1)==-1 && errno==EAGAIN);
  const char sent=42;
  assert(write(gSignalPipe[1],&sent,1)==1);
  assert(read(gSignalPipe[0],&c,1)==1 && c==sent);
  assert(close(gSignalPipe[0])==0 && close(gSignalPipe[1])==0);
 }
}
''')
            compiled = subprocess.run(['clang++', '-std=c++20', '-DORBISFOX_HOMEBREW_SDK=1',
                                       '-fsanitize=address,undefined', str(source), '-o', str(root / 'host')],
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(root / 'host')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
