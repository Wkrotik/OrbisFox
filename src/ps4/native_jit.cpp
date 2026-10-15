#ifdef ORBISFOX_FULL_GECKO
#include "orbisfox/jit_memory_probe.h"
#include "orbisfox/module_binding.h"
#include "orbisfox/presenter.h"
#include "../../gecko/orbisfox/OrbisExecutableMemory.h"
#include <orbis/libkernel.h>
#include <sys/mman.h>
#include <unistd.h>
namespace orbisfox {
namespace {
using Create=int32_t(*)(int,size_t,int,int*);
using Alias=int32_t(*)(int,int,int*);
using Map=int32_t(*)(int,int,void**);
struct Functions {Create create=nullptr;Alias alias=nullptr;Map map=nullptr;};
Functions compilerFunctions; // Compiler callbacks outlive the startup probe.
template<typename T> struct Guard {
  unsigned char before[32];T value;unsigned char after[32];
  explicit Guard(T initial):value(initial){memset(before,0xa5,32);memset(after,0xa5,32);}
  bool intact()const {for(auto byte:before)if(byte!=0xa5)return false;for(auto byte:after)if(byte!=0xa5)return false;return true;}
};
}
bool probe_native_jit_memory() {
  Functions functions;OrbisKernelModule modules[256]{};size_t count=0;
  const auto resolver=ps4_module_backend();
  if(sceKernelGetModuleList(modules,256,&count)!=0 || count>256)return false;
  for(size_t i=0;i<count;++i) {
    OrbisKernelModuleInfo info{};info.size=sizeof(info);
    if(sceKernelGetModuleInfo(modules[i],&info)!=0 || !memchr(info.name,0,sizeof(info.name)))continue;
    const char* name=strrchr(info.name,'/');name=name?name+1:info.name;
    if(strncmp(name,"libkernel",9)!=0)continue;
    void *create=nullptr,*alias=nullptr,*map=nullptr;
    if(!resolver.resolve(resolver.user,modules[i],"sceKernelJitCreateSharedMemory",&create) ||
       !resolver.resolve(resolver.user,modules[i],"sceKernelJitCreateAliasOfSharedMemory",&alias) ||
       !resolver.resolve(resolver.user,modules[i],"sceKernelJitMapSharedMemory",&map))continue;
    functions={reinterpret_cast<Create>(create),reinterpret_cast<Alias>(alias),reinterpret_cast<Map>(map)};break;
  }
  if(!functions.create) {log("Native JIT memory: real executable API symbols unavailable; interpreter retained");return false;}
  JitMemoryBackend backend{&functions,
    [](void* p,int flags,size_t size,int protection,int* fd)->int32_t {
      Guard<int> output(-1);const auto rc=static_cast<Functions*>(p)->create(flags,size,protection,&output.value);
      if(!output.intact())return -1;if(rc==0)*fd=output.value;return rc;
    },
    [](void* p,int fd,int protection,int* alias)->int32_t {
      Guard<int> output(-1);const auto rc=static_cast<Functions*>(p)->alias(fd,protection,&output.value);
      if(!output.intact())return -1;if(rc==0)*alias=output.value;return rc;
    },
    [](void* p,int fd,int protection,void** address)->int32_t {
      Guard<void*> output(nullptr);const auto rc=static_cast<Functions*>(p)->map(fd,protection,&output.value);
      if(!output.intact())return -1;if(rc==0)*address=output.value;return rc;
    },
    [](void*,void* address,size_t size,int expected) {
      void *low=nullptr,*high=nullptr;int32_t protection=0;
      const uintptr_t start=reinterpret_cast<uintptr_t>(address);
      return sceKernelQueryMemoryProtection(address,&low,&high,&protection)==0 &&
        (protection & 7)==expected && start>=reinterpret_cast<uintptr_t>(low) &&
        start<=UINTPTR_MAX-size && start+size<=reinterpret_cast<uintptr_t>(high);
    },
    [](void*,void* address,size_t size){return munmap(address,size);},
    [](void*,int fd){return close(fd);}};
  const auto result=probeJitMemory(backend);
  log("Native JIT memory: %s create=0x%x alias=0x%x RX=0x%x RW=0x%x RX-not-write=%d RW-not-exec=%d shared=%d own-stub=%d patched=%d cleanup=%d; SpiderMonkey JIT remains disabled",
      result.okay?"PASS":"UNAVAILABLE/FAIL",result.create,result.alias,result.mapRX,result.mapRW,
      result.rxNotWritable,result.rwNotExecutable,result.sharedBytes,result.first,result.patched,result.cleanup);
  return result.okay;
}
bool prepare_native_jit_memory() {
  // Do not reuse the old opt-in's stack-local callback state.
  OrbisKernelModule modules[256]{};size_t count=0;const auto resolver=ps4_module_backend();
  if(sceKernelGetModuleList(modules,256,&count)!=0 || count>256)return false;
  for(size_t i=0;i<count;++i){
    OrbisKernelModuleInfo info{};info.size=sizeof(info);
    if(sceKernelGetModuleInfo(modules[i],&info)!=0 || !memchr(info.name,0,sizeof(info.name)))continue;
    const char* name=strrchr(info.name,'/');name=name?name+1:info.name;
    if(strncmp(name,"libkernel",9)!=0)continue;
    void *create=nullptr,*map=nullptr;
    if(!resolver.resolve(resolver.user,modules[i],"sceKernelJitCreateSharedMemory",&create) ||
       !resolver.resolve(resolver.user,modules[i],"sceKernelJitMapSharedMemory",&map))continue;
    compilerFunctions.create=reinterpret_cast<Create>(create);compilerFunctions.map=reinterpret_cast<Map>(map);break;
  }
  if(!compilerFunctions.create || !compilerFunctions.map)return false;
  OrbisJitBackend backend{&compilerFunctions,
    [](void* p,size_t bytes,int* fd)->int32_t {
      Guard<int> output(-1);const auto rc=static_cast<Functions*>(p)->create(0,bytes,7,&output.value);
      if(!output.intact())__builtin_trap();if(rc==0)*fd=output.value;return rc;
    },
    [](void* p,int fd,void** address)->int32_t {
      Guard<void*> output(nullptr);const auto rc=static_cast<Functions*>(p)->map(fd,3,&output.value);
      if(!output.intact())__builtin_trap();if(rc==0)*address=output.value;return rc;
    },
    [](void*,void* address,size_t bytes,int protection)->int32_t {return sceKernelMprotect(address,bytes,protection);},
    [](void*,void* address,size_t bytes,int expected){
      uintptr_t cursor=reinterpret_cast<uintptr_t>(address);
      if(cursor>UINTPTR_MAX-bytes)return false;const uintptr_t end=cursor+bytes;
      for(size_t i=0;cursor<end && i<jitArenaBytes/jitNativePage;++i){
        Guard<void*> low(nullptr),high(nullptr);Guard<int32_t> protection(0);
        const auto rc=sceKernelQueryMemoryProtection(reinterpret_cast<void*>(cursor),&low.value,&high.value,&protection.value);
        if(!low.intact()||!high.intact()||!protection.intact())__builtin_trap();
        const uintptr_t a=reinterpret_cast<uintptr_t>(low.value),b=reinterpret_cast<uintptr_t>(high.value);
        if(rc || (protection.value&7)!=expected || a>cursor || b<=cursor)return false;
        cursor=b<end?b:end;
      }
      return cursor==end;
    },
    [](void*,void* address,size_t bytes)->int32_t {return sceKernelMunmap(address,bytes);},
    [](void*,int fd)->int32_t {return close(fd);}};
  const bool ready=prepare_orbis_executable_memory(backend);const auto state=orbis_jit_memory_stats();
  log("Native baseline JIT gate: %s phase=%u rc=0x%x reserved=%llu; own42/43 single-address RW/RX, never RWX; no kernel patches",
      ready?"PASS":"INTERPRETER FALLBACK",state.failedPhase,unsigned(state.lastResult),(unsigned long long)state.reservedBytes);
  log("Native JIT reason: %s; Wasm remains unavailable until executable code AND native signal/trap contracts are verified; no Wasm interpreter in this engine",
      orbis_jit_gate_reason(state));
  return ready;
}
}
#endif
