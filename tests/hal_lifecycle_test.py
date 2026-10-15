"""Real Orbis app-shell source with explicit HAL/Gecko API doubles, not firmware."""
import os
from pathlib import Path
import resource
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HalLifecycleTest(unittest.TestCase):
    def test_app_shell_owns_hal_before_content_and_releases_on_failed_init(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            common = r'''
#pragma once
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <map>
#include <string>
#include <vector>
using nsresult=int;
constexpr int NS_OK=0;
#define NS_FAILED(x) ((x)!=0)
#define MOZ_ASSERT(x) assert(x)
#define MOZ_RELEASE_ASSERT(x) assert(x)
inline bool NS_IsMainThread(){return true;}
#define printf_stderr(...) std::fprintf(stderr,__VA_ARGS__)
inline std::vector<int> order;
inline bool baseFails=false;
namespace mozilla {
enum MemoryOrdering {Relaxed};
template<class T,MemoryOrdering> class Atomic {
 std::atomic<T> value;
 public: Atomic(T v):value(v){} operator T() const{return value.load();}
 T operator++(){return ++value;} Atomic& operator=(T v){value=v;return *this;}
};
struct MonitorAutoLock {explicit MonitorAutoLock(int&){} void Notify(){} void Wait(){assert(false);}};
template<class T> auto MakeUnique(){return std::make_unique<T>();}
namespace hal {
inline std::unique_ptr<std::map<std::u16string,int>> table;
inline void Init(){assert(!table);table=std::make_unique<std::map<std::u16string,int>>();order.push_back(1);}
inline void Shutdown(){assert(table);table.reset();order.push_back(5);}
inline void VideoWakeLock(){assert(table);++(*table)[u"video-playing"];order.push_back(4);}
}
namespace widget {
struct OrbisEventDiagnostics {uint32_t stage;uint64_t schedules,callbacks;};
class HeadlessScreenHelper {};
class ScreenManager {public:static ScreenManager& GetSingleton(){static ScreenManager s;return s;}void SetHelper(std::unique_ptr<HeadlessScreenHelper>){order.push_back(3);}};
}
}
class nsBaseAppShell {public:virtual ~nsBaseAppShell()=default;nsresult Init(){order.push_back(2);return baseFails?1:0;}void NativeEventCallback(){};};
class nsAppShell:public nsBaseAppShell {
 bool mHalInitialized=false,mPending=false;int mWake=0;
 public:~nsAppShell() override;nsresult Init();void ScheduleNativeEventCallback();bool ProcessNextNativeEvent(bool);
};
'''
            (out / 'common.h').write_text(common)
            for name in ('nsAppShell.h', 'OrbisFoxHost.h', 'nsThreadUtils.h', 'HeadlessScreenHelper.h', 'mozilla/UniquePtr.h', 'mozilla/Hal.h', 'mozilla/Atomics.h', 'nsDebug.h', 'mozilla/widget/ScreenManager.h'):
                target = out / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('#include "common.h"\n')
            harness = out / 'test.cpp'
            harness.write_text(r'''
#include "common.h"
int main(){
 for(int i=0;i<32;++i){
  order.clear();baseFails=false;
  {nsAppShell shell;assert(shell.Init()==NS_OK);assert((order==std::vector<int>{1,2,3}));mozilla::hal::VideoWakeLock();assert((*mozilla::hal::table)[u"video-playing"]==1);shell.ScheduleNativeEventCallback();assert(shell.ProcessNextNativeEvent(false));assert(!shell.ProcessNextNativeEvent(false));}
  assert(!mozilla::hal::table);assert(order.back()==5);
  order.clear();baseFails=true;{nsAppShell shell;assert(shell.Init()!=NS_OK);assert((order==std::vector<int>{1,2}));}assert(!mozilla::hal::table);assert(order.back()==5);
 }
}
''')
            source = ROOT / 'gecko/widget/orbis/nsAppShell.cpp'
            copied_source = out/'fixed.cpp'
            copied_source.write_text(source.read_text())
            compiler = os.environ.get('HOST_CXX', 'clang++')
            command = [compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-I'+str(out), str(copied_source), str(harness), '-o', str(out/'fixed')]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(out/'fixed')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            reference = out/'uninitialized.cpp'
            reference.write_text(source.read_text().replace('  mozilla::hal::Init();', '  /* original missing HAL initialization */', 1))
            command[-4] = str(reference)
            command[-1] = str(out/'uninitialized')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(out/'uninitialized')], capture_output=True, text=True, preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0)))
            self.assertNotEqual(result.returncode, 0, 'Reference must expose the missing HAL lifecycle')
            self.assertIn('order==std::vector<int>{1,2,3}', result.stderr)


if __name__ == '__main__':
    unittest.main()
