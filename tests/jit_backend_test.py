import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class JitBackendTest(unittest.TestCase):
    def test_owned_single_address_code_transitions_and_failures(self):
        source = r'''
#include "OrbisExecutableMemory.h"
#include <cassert>
#include <cerrno>
#include <cstring>
#include <initializer_list>
#include <sys/mman.h>
#include <unistd.h>
using namespace orbisfox;
struct Fake {
 int fail=0,createCalls=0,mapCalls=0,protectCalls=0,queryCalls=0,files=0,maps=0;int32_t createResult=-ENOMEM;void* base=nullptr;
 unsigned char protections[jitArenaBytes/jitNativePage]{};
};
static OrbisJitBackend adapter(Fake& f){return {&f,
 [](void* u,size_t n,int* fd)->int32_t {auto& f=*static_cast<Fake*>(u);assert(n==jitArenaBytes);++f.createCalls;if(f.fail==1)return f.createResult;
  *fd=memfd_create("owned-code-test",0);assert(*fd>=0&&ftruncate(*fd,n)==0);++f.files;return 0;},
 [](void* u,int fd,void** a)->int32_t {auto& f=*static_cast<Fake*>(u);++f.mapCalls;if(f.fail==2)return -ENOMEM;
  void* reservation=mmap(nullptr,jitArenaBytes+jitNativePage,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(reservation!=MAP_FAILED);
  const uintptr_t start=reinterpret_cast<uintptr_t>(reservation),aligned=(start+jitNativePage-1)&~uintptr_t(jitNativePage-1);
  *a=mmap(reinterpret_cast<void*>(aligned),jitArenaBytes,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_FIXED,fd,0);assert(*a==reinterpret_cast<void*>(aligned));
  if(aligned>start)assert(munmap(reservation,aligned-start)==0);
  const uintptr_t end=aligned+jitArenaBytes,limit=start+jitArenaBytes+jitNativePage;
  if(end<limit)assert(munmap(reinterpret_cast<void*>(end),limit-end)==0);
  f.base=*a;++f.maps;memset(f.protections,3,sizeof(f.protections));return 0;},
 [](void* u,void* a,size_t n,int p)->int32_t {auto& f=*static_cast<Fake*>(u);++f.protectCalls;
  assert(p==0||p==3||p==5);if(f.fail==f.protectCalls+2)return -EPERM;
  assert(mprotect(a,n,p)==0);const size_t first=(static_cast<char*>(a)-static_cast<char*>(f.base))/jitNativePage;
  memset(f.protections+first,p,n/jitNativePage);return 0;},
 [](void* u,void* a,size_t n,int p){auto& f=*static_cast<Fake*>(u);++f.queryCalls;if(f.fail==7)return false;
  const size_t first=(static_cast<char*>(a)-static_cast<char*>(f.base))/jitNativePage;
  for(size_t i=first;i<first+n/jitNativePage;++i)if(f.protections[i]!=p)return false;return true;},
 [](void* u,void* a,size_t n)->int32_t {auto& f=*static_cast<Fake*>(u);assert(a==f.base&&n==jitArenaBytes);assert(munmap(a,n)==0);--f.maps;f.base=nullptr;return 0;},
 [](void* u,int fd)->int32_t {auto& f=*static_cast<Fake*>(u);assert(close(fd)==0);--f.files;return 0;}};}
int main(){
 for(int failure=1;failure<=7;++failure){Fake f;f.fail=failure;assert(!prepare_orbis_executable_memory(adapter(f)));assert(!f.maps&&!f.files);assert(!orbis_jit_memory_stats().ready);shutdown_orbis_executable_memory();}
 // The exact native denial must stop before mapping/protecting/executing,
 // preserve its raw code, and never produce a claimed executable arena.
 for(int32_t denied:{int32_t(-EPERM),int32_t(0x80020001u)}){
  Fake deniedState;deniedState.fail=1;deniedState.createResult=denied;
  assert(!prepare_orbis_executable_memory(adapter(deniedState)));
  const auto deniedStats=orbis_jit_memory_stats();assert(deniedStats.failedPhase==1&&deniedStats.lastResult==denied&&!deniedStats.ready&&!deniedStats.claimed);
  assert(!strcmp(orbis_jit_gate_reason(deniedStats),"shared-code-permission-denied"));
  assert(deniedState.createCalls==1&&!deniedState.mapCalls&&!deniedState.protectCalls&&!deniedState.queryCalls&&!deniedState.maps&&!deniedState.files);
  assert(!reserve_orbis_executable_memory(jitArenaBytes));shutdown_orbis_executable_memory();
 }
 Fake f;assert(prepare_orbis_executable_memory(adapter(f)));assert(f.protectCalls==4&&f.maps==1&&f.files==1);
 assert(orbis_jit_memory_stats().reservedBytes==jitArenaBytes);assert(!reserve_orbis_executable_memory(123));
 void* base=reserve_orbis_executable_memory(jitArenaBytes);assert(base==f.base);assert(!reserve_orbis_executable_memory(jitArenaBytes));
 assert(!protect_orbis_executable_memory(base,jitNativePage,7));assert(!protect_orbis_executable_memory(static_cast<char*>(base)+1,jitNativePage,3));
 assert(!protect_orbis_executable_memory(static_cast<char*>(base)+jitArenaBytes,jitNativePage,3));
 assert(protect_orbis_executable_memory(base,jitNativePage,3));
 const unsigned char code[]={0xb8,57,0,0,0,0xc3};memcpy(static_cast<char*>(base)+64,code,sizeof(code));
 assert(protect_orbis_executable_memory(base,jitNativePage,5));assert(reinterpret_cast<int(*)()>(static_cast<char*>(base)+64)()==57);
 assert(orbis_jit_memory_stats().committedBytes==jitNativePage);
 assert(protect_orbis_executable_memory(base,jitNativePage,0));assert(!orbis_jit_memory_stats().committedBytes);
 release_orbis_executable_memory(base,jitArenaBytes);assert(!f.maps&&!f.files&&!orbis_jit_memory_stats().ready);
 // A repeated startup is independent and does not retain old mappings/fds.
 assert(prepare_orbis_executable_memory(adapter(f)));shutdown_orbis_executable_memory();assert(!f.maps&&!f.files);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = pathlib.Path(directory) / 'test.cpp'
            binary = pathlib.Path(directory) / 'test'
            cpp.write_text(source)
            command = ['clang++', '-std=c++17', '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Werror',
                       '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
                       '-I', str(ROOT / 'gecko/orbisfox'), str(cpp),
                       str(ROOT / 'gecko/orbisfox/OrbisExecutableMemory.cpp'), '-o', str(binary)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
