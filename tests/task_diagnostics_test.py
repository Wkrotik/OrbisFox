"""Actual task-span implementation with explicit runnable/refcount/API doubles.
Red/green proves lifetime; phase checks use a fake clock, not firmware timing.
"""
import os
import resource
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TaskDiagnosticsTest(unittest.TestCase):
    def test_runnable_release_before_long_span_destructor(self):
        compiler = shutil.which('clang++')
        if not compiler:
            self.skipTest('clang++ unavailable')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'nsString.h').write_text(r'''
#pragma once
#include <string>
class nsAutoCString {
 std::string text;
 public:
 void AssignLiteral(const char* value){text=value;}
 const char* BeginReading() const{return text.data();}
 const char* EndReading() const{return text.data()+text.size();}
};
#define NS_FAILED(result) ((result)<0)
''')
            (path / 'nsIRunnable.h').write_text(r'''
#pragma once
class nsINamed;
class nsIRunnable {
 public:
 virtual void AddRef()=0;
 virtual void Release()=0;
 virtual void Run()=0;
 virtual nsINamed* QueryNamed()=0;
 protected: virtual ~nsIRunnable()=default;
};
''')
            (path / 'nsINamed.h').write_text(r'''
#pragma once
#include "nsString.h"
class nsINamed {
 public:
 virtual void AddRef()=0;
 virtual void Release()=0;
 virtual int GetName(nsAutoCString&)=0;
 protected: virtual ~nsINamed()=default;
};
''')
            (path / 'nsCOMPtr.h').write_text(r'''
#pragma once
#include "nsIRunnable.h"
struct Query {nsIRunnable* value;};
template<class T> class nsCOMPtr {
 T* value=nullptr;
 public:
 nsCOMPtr()=default;
 nsCOMPtr(T* pointer):value(pointer){if(value)value->AddRef();}
 nsCOMPtr(Query query){value=query.value?query.value->QueryNamed():nullptr;}
 ~nsCOMPtr(){if(value)value->Release();}
 nsCOMPtr(const nsCOMPtr& other):nsCOMPtr(other.value){}
 nsCOMPtr& operator=(decltype(nullptr)){T* old=value;value=nullptr;if(old)old->Release();return *this;}
 T* operator->()const{return value;}
 operator T*()const{return value;}
};
inline Query do_QueryInterface(nsIRunnable* pointer){return {pointer};}
''')
            (path / 'nsThreadUtils.h').write_text(r'''
#pragma once
extern bool testMain;
inline bool NS_IsMainThread(){return testMain;}
''')
            (path / 'test.cpp').write_text(r'''
#include "OrbisTaskDiagnostics.h"
#include "nsIRunnable.h"
#include "nsINamed.h"
#include <cassert>
#include <cstring>
#include <cstdint>
#include <type_traits>
#include <cstdio>
#include <string>
#include "completed-tasks.inc"
using namespace mozilla::widget;
static uint64_t clockNow=100;
bool testMain=true;
static unsigned clockReads=0;
extern "C" uint64_t sceKernelGetProcessTime(){++clockReads;return clockNow;}
static unsigned destroyed=0,names=0;
struct Runnable final:nsIRunnable,nsINamed {
 unsigned references=0;
 void AddRef()override{++references;}
 void Release()override{assert(references);if(!--references)delete this;}
 void Run()override{clockNow+=300000;}
 nsINamed* QueryNamed()override{AddRef();return this;}
 int GetName(nsAutoCString& output)override{++names;output.AssignLiteral("lifetime-regression-task");return 0;}
 ~Runnable()override{++destroyed;}
};
int main(){
#ifndef TEST_UNFIXED
 static_assert(!std::is_copy_constructible_v<OrbisMainTaskSpan>);
 static_assert(!std::is_copy_assignable_v<OrbisMainTaskSpan>);
#endif
 // Same ordering as real RunnableTask::Run: clear owner before span destruction.
 for(unsigned i=0;i<32;++i){
  nsCOMPtr<nsIRunnable> runnable=new Runnable();
  {OrbisMainTaskSpan span(runnable,true);runnable->Run();runnable=nullptr;}
  assert(destroyed==i+1);
 }
 auto stats=GetOrbisTaskDiagnostics();
 assert(stats.events==32&&stats.longEvents==32&&stats.depth==0&&stats.activeStart==0);
 assert(stats.lastDetailedMicros==300000);
 assert(!strcmp(stats.lastDetailedName,"lifetime-regression-task"));
 assert(names==32);
 assert(stats.completedCount==16&&stats.completedSerial==32);
 for(unsigned i=0;i<stats.completedCount;++i){
  const auto& task=stats.completed[i];
  assert(task.serial==17+i&&task.micros==300000&&task.depth==1&&task.detailed);
  assert(task.ended==100+task.serial*300000);
  assert(!strcmp(task.name,"lifetime-regression-task"));
 }
 FILE* output=tmpfile();assert(output);uint64_t cursor=0;
 writeCompletedTasks(output,stats,cursor);assert(cursor==32);
 const long first=ftell(output);writeCompletedTasks(output,stats,cursor);assert(ftell(output)==first);
 rewind(output);std::string text;char line[512];while(fgets(line,sizeof(line),output))text+=line;
 assert(text.find("main-task-history lost=16")!=std::string::npos);
 assert(text.find("main-task-complete id=17 end-us=5100100 inclusive-us=300000 depth=1 detailed=1 name=lifetime-regression-task")!=std::string::npos);
 fclose(output);
 {nsCOMPtr<nsIRunnable> runnable=new Runnable();OrbisMainTaskSpan span(runnable);clockNow+=1;runnable=nullptr;}
 assert(destroyed==33&&names==32);
 // Nested event spans restore the outer start and balance depth.
 {nsCOMPtr<nsIRunnable> runnable=new Runnable();OrbisMainTaskSpan outer(runnable);
  const auto before=GetOrbisTaskDiagnostics();assert(before.depth==1);
  {OrbisMainTaskSpan inner(runnable);clockNow+=10;assert(GetOrbisTaskDiagnostics().depth==2);}
  const auto after=GetOrbisTaskDiagnostics();assert(after.depth==1&&after.activeStart==before.activeStart);
 }
 // Worker thread spans neither modify counters nor perform name lookup.
 const auto before=GetOrbisTaskDiagnostics();testMain=false;
 {nsCOMPtr<nsIRunnable> runnable=new Runnable();OrbisMainTaskSpan span(runnable,true);runnable->Run();runnable=nullptr;}
 const auto after=GetOrbisTaskDiagnostics();
 assert(after.events==before.events&&after.longEvents==before.longEvents&&after.depth==0);
 assert(destroyed==35&&names==32);
 testMain=true;
 // Nested records are inclusive, ordered by completion, and identify depth.
 {nsCOMPtr<nsIRunnable> runnable=new Runnable();OrbisMainTaskSpan outer(runnable);
  {OrbisMainTaskSpan inner(runnable,true);clockNow+=250000;}
  clockNow+=100000;
 }
 stats=GetOrbisTaskDiagnostics();assert(stats.completedSerial==34&&stats.completedCount==16);
 assert(stats.completed[14].depth==2&&stats.completed[14].micros==250000&&stats.completed[14].detailed);
 assert(stats.completed[15].depth==1&&stats.completed[15].micros==350000&&!stats.completed[15].detailed);
 output=tmpfile();assert(output);writeCompletedTasks(output,stats,cursor);assert(cursor==34);
 rewind(output);text.clear();while(fgets(line,sizeof(line),output))text+=line;
 assert(text.find("lost=")==std::string::npos&&text.find("id=33 ")!=std::string::npos);
 assert(text.find("id=32 ")==std::string::npos);fclose(output);
 // A backwards clock cannot create a bogus long completion.
 {nsCOMPtr<nsIRunnable> runnable=new Runnable();OrbisMainTaskSpan span(runnable);--clockNow;}
 assert(GetOrbisTaskDiagnostics().completedSerial==34);
 // Phase observation is disabled without opt-in, including process clock reads.
 auto pump=GetOrbisPumpDiagnostics();assert(pump.phase==0&&pump.activeStart==0);
 const auto reads=clockReads;
 {OrbisPumpSpan disabled(false);clockNow+=10;disabled.SetPhase(OrbisPumpPhase::Input);}
 assert(clockReads==reads&&GetOrbisPumpDiagnostics().phase==0);
 testMain=false;
 {OrbisPumpSpan worker(true);worker.SetPhase(OrbisPumpPhase::Input);}
 assert(clockReads==reads);testMain=true;
 {
  OrbisPumpSpan outer(true);clockNow+=10;outer.SetPhase(OrbisPumpPhase::Input);
  const auto parent=GetOrbisPumpDiagnostics();assert(parent.phase==2);
  clockNow+=20;
  {OrbisPumpSpan nested(true);clockNow+=30;nested.SetPhase(OrbisPumpPhase::Map);clockNow+=40;}
  pump=GetOrbisPumpDiagnostics();assert(pump.phase==2&&pump.activeStart==parent.activeStart);
  clockNow+=50;outer.SetPhase(OrbisPumpPhase::Mailbox);
  pump=GetOrbisPumpDiagnostics();assert(pump.lastMicros[2]==140&&pump.lastMicros[4]==40);
  clockNow+=7;outer.SetPhase(OrbisPumpPhase::Present);clockNow+=11;
 }
 pump=GetOrbisPumpDiagnostics();assert(pump.phase==0&&pump.activeStart==0);
 assert(pump.lastMicros[1]==30&&pump.lastMicros[3]==7&&pump.lastMicros[5]==11);
 assert(pump.maxMicros[2]==140&&pump.maxMicros[4]==40);
 {OrbisPumpSpan backwards(true);--clockNow;}
 pump=GetOrbisPumpDiagnostics();assert(pump.lastMicros[1]==0&&pump.maxMicros[1]==30&&pump.phase==0);
 const auto fail=[](){OrbisPumpSpan scope(true);scope.SetPhase(OrbisPumpPhase::Map);clockNow+=9;return -1;};
 assert(fail()==-1);pump=GetOrbisPumpDiagnostics();
 assert(pump.phase==0&&pump.activeStart==0&&pump.lastMicros[4]==9&&pump.maxMicros[4]==40);
}
''')
            native = (ROOT / 'gecko/orbisfox/native/main.cpp').read_text()
            writer = native[native.index('void writeCompletedTasks('):native.index('void* monitor(')]
            (path / 'completed-tasks.inc').write_text(writer)
            source = ROOT / 'gecko/widget/orbis/OrbisTaskDiagnostics.cpp'
            header = ROOT / 'gecko/widget/orbis/OrbisTaskDiagnostics.h'
            shutil.copy2(header, path / header.name)
            fixed = path / 'fixed'
            flags = [compiler, '-std=c++20', '-Wall', '-Wextra', '-Werror', '-g',
                     '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
                     '-I' + str(path)]
            # Copy the real implementation so its local include selects private
            # headers, without mutating canonical or prepared Gecko sources.
            shutil.copy2(source, path / source.name)
            subprocess.run(flags + [str(path / source.name), str(path / 'test.cpp'), '-o', str(fixed)],
                           check=True, capture_output=True, text=True)
            environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=0')
            green = subprocess.run([str(fixed)], capture_output=True, text=True, env=environment, check=False)
            self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
            # Isolate only the old borrowed-reference defect in a private build.
            text = (path / header.name).read_text()
            self.assertEqual(text.count('nsCOMPtr<nsIRunnable> task_;'), 1)
            (path / header.name).write_text(text.replace('nsCOMPtr<nsIRunnable> task_;', 'nsIRunnable* task_;'))
            unfixed = path / 'unfixed'
            subprocess.run(flags + ['-DTEST_UNFIXED', str(path / source.name), str(path / 'test.cpp'), '-o', str(unfixed)],
                           check=True, capture_output=True, text=True)
            def no_core():
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            red = subprocess.run([str(unfixed)], capture_output=True, text=True,
                                 env=environment, preexec_fn=no_core, check=False)
            self.assertNotEqual(red.returncode, 0)
            self.assertIn('heap-use-after-free', red.stderr)


if __name__ == '__main__':
    unittest.main()
