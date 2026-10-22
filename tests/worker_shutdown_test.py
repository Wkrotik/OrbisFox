"""Actual patched worker-finish body with explicit thread/ACK ownership doubles.
No claim of real Gecko event-loop, pthread, or console shutdown validation.
"""
import os
import resource
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = '''#include "nsISupportsPriority.h"
NS_IMETHODIMP
WorkerThreadPrimaryRunnable::FinishedRunnable::Run() {
  AssertIsOnMainThread();

  SafeRefPtr<WorkerThread> thread = std::move(mThread);
  if (thread->ShutdownRequired()) {
    MOZ_ALWAYS_SUCCEEDS(thread->Shutdown());
  }

  return NS_OK;
}

}  // namespace workerinternals
'''


class WorkerShutdownTest(unittest.TestCase):
    def patch_fixture(self, directory):
        source = directory / 'dom/workers/RuntimeService.cpp'
        source.parent.mkdir(parents=True)
        source.write_text(ORIGINAL)
        patch = runpy.run_path(str(ROOT / 'scripts/patch-gecko-layout.py'))['patch_native_worker_shutdown']
        patch(directory)
        return source, patch

    def test_patch_is_byte_and_mtime_stable_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, patch = self.patch_fixture(root)
            text, timestamp = source.read_bytes(), source.stat().st_mtime_ns
            patch(root)
            self.assertEqual(source.read_bytes(), text)
            self.assertEqual(source.stat().st_mtime_ns, timestamp)
            source.write_text(ORIGINAL.replace('thread->Shutdown()', 'thread->ChangedShutdownAPI()'))
            with self.assertRaisesRegex(RuntimeError, 'Pinned Gecko layout patch no longer matches'):
                patch(root)

    def test_link_gate_avoids_temporary_debug_only_for_native_sdk(self):
        patch = runpy.run_path(str(ROOT / 'scripts/patch-gecko-layout.py'))['patch_native_link_gate_debug']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'toolkit/library/build/moz.build'
            source.parent.mkdir(parents=True)
            source.write_text('Libxul("xul-real")\n')
            patch(root)
            content, timestamp = source.read_bytes(), source.stat().st_mtime_ns
            patch(root)
            self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), (content, timestamp))
            for native in (False, True):
                flags = []
                exec(source.read_text(), {'Libxul': lambda name: None,
                                         'CONFIG': {'MOZ_ORBIS_HOMEBREW_SDK': native}, 'LDFLAGS': flags})
                self.assertEqual(flags, ['-Wl,--strip-debug'] if native else [])
            source.write_text('Libxul("changed")\n')
            with self.assertRaisesRegex(RuntimeError, 'Pinned Gecko layout patch no longer matches'):
                patch(root)

    def test_finished_worker_uses_checked_owned_async_handshake(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('clang++ unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            patched, _ = self.patch_fixture(root)
            body = patched.read_text().split('NS_IMETHODIMP\n', 1)[1].split('\n}  // namespace workerinternals', 1)[0]
            harness = root / 'worker.cpp'
            harness.write_text(r'''
#include <cassert>
#include <memory>
#include <utility>
#include <vector>
#define NS_OK 0
static void AssertIsOnMainThread(){}
struct CheckedFailure {};
static void Check(int result){if(result!=0)throw CheckedFailure{};}
#define MOZ_ALWAYS_SUCCEEDS(call) Check(call)
template<class T> using SafeRefPtr=std::shared_ptr<T>;
template<class T> using nsCOMPtr=std::shared_ptr<T>;
template<class T> auto& getter_AddRefs(std::shared_ptr<T>& target){return target;}
struct WorkerThread;
struct nsIThreadShutdown {std::shared_ptr<WorkerThread> thread;};
static std::vector<std::shared_ptr<nsIThreadShutdown>> pending;
static unsigned begins=0,synchronous=0,nestedPumps=0,joins=0,destroyed=0;
static bool failBegin=false,failSync=false;
struct WorkerThread:std::enable_shared_from_this<WorkerThread> {
 bool required=true;
 bool ShutdownRequired()const{return required;}
 int BeginShutdown(std::shared_ptr<nsIThreadShutdown>& result){
  ++begins;if(failBegin)return -1;
  required=false;result=std::make_shared<nsIThreadShutdown>();
  result->thread=shared_from_this();pending.push_back(result);return NS_OK;
 }
 int Shutdown(){++synchronous;if(failSync)return -1;required=false;++nestedPumps;++joins;return NS_OK;}
 ~WorkerThread(){++destroyed;}
};
struct WorkerThreadPrimaryRunnable {
 struct FinishedRunnable {std::shared_ptr<WorkerThread> mThread;int Run();};
};
int
''' + body + r'''
void ackAll(){for(auto& context:pending){assert(context->thread);++joins;}pending.clear();}
int main(){
 for(unsigned cycle=0;cycle<64;++cycle){
  begins=synchronous=nestedPumps=joins=destroyed=0;
  auto thread=std::make_shared<WorkerThread>();std::weak_ptr<WorkerThread> observer=thread;
  WorkerThreadPrimaryRunnable::FinishedRunnable task{thread};thread.reset();
  assert(task.Run()==NS_OK&&!task.mThread);
#ifdef MOZ_ORBIS_HOMEBREW_SDK
  // The local out-parameter has gone, but the outstanding ACK owns the thread.
  assert(begins==1&&synchronous==0&&nestedPumps==0&&joins==0);
  assert(pending.size()==1&&!observer.expired()&&destroyed==0);
  ackAll();assert(observer.expired()&&joins==1&&destroyed==1);
#else
  assert(begins==0&&synchronous==1&&nestedPumps==1&&joins==1);
  assert(pending.empty()&&observer.expired()&&destroyed==1);
#endif
  // Already-recycled threads must not request a second shutdown.
  auto idle=std::make_shared<WorkerThread>();idle->required=false;
  WorkerThreadPrimaryRunnable::FinishedRunnable recycled{idle};
  auto oldBegins=begins,oldSync=synchronous;
  assert(recycled.Run()==NS_OK&&!recycled.mThread);
  assert(begins==oldBegins&&synchronous==oldSync&&pending.empty());idle.reset();
  // A rejected handshake stays checked: no fake success, fallback or leaked ACK.
  auto failing=std::make_shared<WorkerThread>();
  WorkerThreadPrimaryRunnable::FinishedRunnable rejected{failing};
  failBegin=failSync=true;bool checked=false;
  try{rejected.Run();}catch(const CheckedFailure&){checked=true;}
  assert(checked&&pending.empty());failBegin=failSync=false;failing.reset();
 }
}
''')
            environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1')

            def no_core():
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

            for native in (False, True):
                binary = root / ('native' if native else 'legacy')
                command = [compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined']
                if native:
                    command.append('-DMOZ_ORBIS_HOMEBREW_SDK=1')
                subprocess.run([*command, str(harness), '-o', str(binary)], check=True, capture_output=True, text=True)
                subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=15,
                               env=environment, preexec_fn=no_core)
            original_body = ORIGINAL.split('NS_IMETHODIMP\n', 1)[1].split('\n}  // namespace workerinternals', 1)[0]
            harness.write_text(harness.read_text().replace(body, original_body, 1))
            red = root / 'unpatched-native'
            subprocess.run([compiler, '-std=c++17', '-O1', '-g', '-DMOZ_ORBIS_HOMEBREW_SDK=1',
                            '-fsanitize=address,undefined', str(harness), '-o', str(red)],
                           check=True, capture_output=True, text=True)
            result = subprocess.run([str(red)], check=False, capture_output=True, text=True, timeout=15,
                                    env=environment, preexec_fn=no_core)
            self.assertNotEqual(result.returncode, 0, 'original synchronous body must fail the async ownership contract')
            self.assertIn('begins==1', result.stderr)


if __name__ == '__main__':
    unittest.main()
