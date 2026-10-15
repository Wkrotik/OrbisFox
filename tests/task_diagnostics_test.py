"""Actual task-span implementation with explicit runnable/refcount/API doubles.
Red/green proves lifetime only, not Gecko event dispatch or firmware timing.
"""
import os
from pathlib import Path
import resource
import shutil
import subprocess
import tempfile
import unittest

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
using namespace mozilla::widget;
static uint64_t clockNow=100;
bool testMain=true;
extern "C" uint64_t sceKernelGetProcessTime(){return clockNow;}
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
}
''')
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
            green = subprocess.run([str(fixed)], capture_output=True, text=True, env=environment)
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
                                 env=environment, preexec_fn=no_core)
            self.assertNotEqual(red.returncode, 0)
            self.assertIn('heap-use-after-free', red.stderr)


if __name__ == '__main__':
    unittest.main()
