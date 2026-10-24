# SPDX-License-Identifier: MIT
"""Allocation-neutral boundary observations, not a reproduction of console corruption."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from mesa_native_test import builder, DISPATCH_CORE, DISPATCH_CONTEXT

ROOT=Path(__file__).resolve().parent.parent


class MesaDispatchTests(unittest.TestCase):
    def compile_run(self,source,extra=()):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cpp=root/'test.cpp';binary=root/'test';cpp.write_text(source)
            subprocess.run(['clang++','-std=c++20','-Wall','-Wextra','-Werror','-O1','-g',
                '-fsanitize=address,undefined','-fno-omit-frame-pointer','-pthread',
                '-I'+str(ROOT/'include'),cpp,*extra,'-o',binary],check=True)
            subprocess.run([binary],check=True)

    def test_generated_writes_keep_original_allocation_and_null_behavior(self):
        core=builder.patch_dispatch(DISPATCH_CORE,builder.DISPATCH_FILES[0])
        context=builder.patch_dispatch(DISPATCH_CONTEXT,builder.DISPATCH_FILES[1])
        self.compile_run(r'''
#include "orbisfox/mesa_binding.h"
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cerrno>
using _glapi_proc=void (*)();
constexpr unsigned _gloffset_COUNT=1639;
struct _glapi_table {_glapi_proc entries[_gloffset_COUNT];};
static _glapi_proc table_noop_array[_gloffset_COUNT]{};
static void glthread_nop(){}
static bool fail=false;static unsigned allocations=0,seen=0;
static _glapi_table* allocation=nullptr;
_glapi_table* table_malloc(size_t n){assert(n==sizeof(_glapi_table));++allocations;
 return allocation=fail?nullptr:static_cast<_glapi_table*>(std::malloc(n));}
void observe(void* p,size_t n,unsigned phase){assert(n==sizeof(_glapi_table));assert(p==allocation);
 assert(phase==++seen);if(phase==1){assert(allocations==1);} // no relocation
 if(p&&phase==2)for(unsigned i=0;i<_gloffset_COUNT;++i)assert(static_cast<_glapi_table*>(p)->entries[i]==nullptr);
 if(p&&phase==4)for(unsigned i=0;i<_gloffset_COUNT;++i)assert(static_cast<_glapi_table*>(p)->entries[i]==glthread_nop);
}
extern "C" {
#define malloc table_malloc
'''+core+'\n'+context+r'''
#undef malloc
}
int main(){
 // The strict XUL gate and diagnostics-off observer do not require native state.
 assert(orbis_mesa_dispatch_observer==nullptr);
 auto* table=_mesa_new_nop_table(true);assert(table==allocation&&allocations==1&&seen==0);std::free(table);
 allocations=0;orbis_mesa_dispatch_observer=observe;
 table=_mesa_new_nop_table(true);assert(table==allocation&&allocations==1&&seen==4);std::free(table);
 allocations=seen=0;table=_mesa_new_nop_table(false);assert(table==allocation&&allocations==1&&seen==2);std::free(table);
 allocations=seen=0;fail=true;
 table=_mesa_new_nop_table(false);assert(table==nullptr&&allocations==1&&seen==2);
}
''',[ROOT/'src/ps4/mesa_runtime_bridge.cpp'])

    def test_broader_boundaries_follow_existing_diagnostics_switch(self):
        source=(ROOT/'src/ps4/native_allocator.cpp').read_text()
        start=source.index('bool auditAllBoundaries(){')
        end=source.index('#ifdef ORBISFOX_NATIVE_RUN_LOGS\norbisfox::AllocatorFlightBuffer',start)
        self.compile_run(r'''
#define ORBISFOX_NATIVE_RUN_LOGS 1
#include <cassert>
bool allApiAudit=true,mesaBoundaryAudit=false,enabled=false;
unsigned queries=0;
namespace orbisfox {bool native_diagnostics_enabled(){++queries;return enabled;}}
'''+source[start:end]+r'''
int main(){
 assert(auditAllBoundaries()&&queries==0); // Original startup checks independent of diagnostics.
 allApiAudit=false;assert(!auditAllBoundaries()&&queries==0); // Ordinary browser unchanged.
 mesaBoundaryAudit=true;assert(!auditAllBoundaries()&&queries==1);
 enabled=true;assert(auditAllBoundaries()&&queries==2);
 enabled=false;assert(!auditAllBoundaries()&&queries==3); // No sticky forced-on capture flag.
}
''')

    def test_actual_native_checkpoint_off_capacity_bound_errno_and_concurrency(self):
        source=(ROOT/'src/ps4/native_allocator.cpp').read_text()
        start=source.index('void checkpoint_native_mesa_dispatch(')
        end=source.index('\n#endif\nbool configure_native_allocator_diagnostics',start)
        function=source[start:end]
        self.compile_run(r'''
#define ORBISFOX_NATIVE_RUN_LOGS 1
#include "orbisfox/heap_diagnostics.h"
#include <cassert>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <mutex>
#include <thread>
#include <sys/wait.h>
#include <sys/resource.h>
#include <unistd.h>
#include <signal.h>
static bool enabled=false,guarded=false,corrupt=false;
static unsigned locks=0,audits=0,queries=0,guardQueries=0,records=0,dispatchRecords=0;
static std::mutex mutex;
struct DispatchContext {uintptr_t table;size_t bytes,capacity;unsigned phase;} lastDispatch{};
constexpr size_t capacity=13112;
bool native_diagnostics_enabled(){return enabled;}
struct HeapLock {uintptr_t site=19,output=0;uint64_t extra=0;HeapLock(const char*,uintptr_t,void*,size_t){mutex.lock();++locks;errno=EIO;}~HeapLock(){errno=ERANGE;mutex.unlock();}};
uintptr_t caller(void* p){return reinterpret_cast<uintptr_t>(p);}
void auditBins(const char*,uintptr_t,const char*){++audits;if(corrupt)__builtin_trap();}
size_t __real_malloc_usable_size(void* p){assert(p);++queries;errno=ENOMEM;return capacity;}
struct Diagnostics {bool enabled(){return guarded;}
 template<class F> size_t usable(void* p,uintptr_t,F){assert(p);++guardQueries;return capacity-32;}
} diagnostics;
void native_write_heap_audit(const char* p,size_t n){++records;assert(n&&p[n-1]=='\n');
 assert(strncmp(p,"ORBISFOX MESA DISPATCH:",22)==0);errno=ENOSPC;}
void fault(const char*,const orbisfox::HeapDiagnosticEvent&){__builtin_trap();}
'''+function+r'''
int main(){
 int table=0;errno=EDOM;checkpoint_native_mesa_dispatch(&table,capacity,1);
 assert(errno==EDOM&&locks==0&&audits==0&&queries==0&&records==0);
 enabled=true;checkpoint_native_mesa_dispatch(&table,capacity,1);
 assert(errno==EDOM&&queries==1&&audits==2&&records==1);
 guarded=true;checkpoint_native_mesa_dispatch(&table,capacity-32,2);
 assert(errno==EDOM&&queries==1&&guardQueries==1&&lastDispatch.capacity==capacity-32);
 guarded=false;checkpoint_native_mesa_dispatch(nullptr,capacity,1);assert(queries==1&&lastDispatch.capacity==0);
 // The child must stop BEFORE querying malformed metadata, not turn it into a capacity.
 for(bool badBins:{false,true}){
  pid_t child=fork();assert(child>=0);
  if(!child){rlimit limit{0,0};assert(setrlimit(RLIMIT_CORE,&limit)==0);signal(SIGILL,SIG_DFL);
   corrupt=badBins;checkpoint_native_mesa_dispatch(&table,capacity+1,3);_exit(8);}
  int status=0;assert(waitpid(child,&status,0)==child);assert(WIFSIGNALED(status)&&WTERMSIG(status)==SIGILL);
 }
 const unsigned before=audits;std::thread workers[4];
 for(auto& worker:workers)worker=std::thread([&]{errno=ECHILD;for(unsigned i=0;i<1000;++i)checkpoint_native_mesa_dispatch(&table,capacity,4);assert(errno==ECHILD);});
 for(auto& worker:workers)worker.join();
 assert(records==128&&dispatchRecords==128&&audits==before+8000);
 assert(lastDispatch.table==reinterpret_cast<uintptr_t>(&table)&&lastDispatch.phase==4);
}
''')


if __name__=='__main__':unittest.main()
