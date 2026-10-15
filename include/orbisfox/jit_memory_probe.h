#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
namespace orbisfox {
// Public reverse-engineered ABI reference: CTurt/PS4-SDK libPS4/source/jit.c.
// This probes native memory only, not SpiderMonkey Baseline/Ion execution.
struct JitMemoryBackend {
  void* context;
  int32_t (*create)(void*,int,size_t,int,int*);
  int32_t (*alias)(void*,int,int,int*);
  int32_t (*map)(void*,int,int,void**);
  bool (*protection)(void*,void*,size_t,int);
  int (*unmap)(void*,void*,size_t);
  int (*close)(void*,int);
};
struct JitMemoryResult {
  bool okay=false;
  int32_t create=-1,alias=-1,mapRX=-1,mapRW=-1;
  int first=-1,patched=-1;
  bool sharedBytes=false,rxNotWritable=false,rwNotExecutable=false,cleanup=true;
};
inline void synchronizeJitInstructions() {
  unsigned a=0,b=0,c=0,d=0;
  __asm__ volatile("cpuid":"+a"(a),"=b"(b),"=c"(c),"=d"(d)::"memory");
}
// Generated stubs have no compiler-inserted function-sanitizer prefix.
#if defined(__clang__)
__attribute__((no_sanitize("function")))
#endif
inline int invokeOwnedJitStub(void* address) {
  return reinterpret_cast<int(*)()>(address)();
}
inline JitMemoryResult probeJitMemory(const JitMemoryBackend& backend) {
  constexpr size_t page=16384;
  constexpr int read=1,write=2,execute=4;
  JitMemoryResult result;
  int fd=-1,alias=-1;void *rx=nullptr,*rw=nullptr;
  do {
    result.create=backend.create(backend.context,0,page,read|write|execute,&fd);
    if(result.create!=0 || fd<0)break;
    result.alias=backend.alias(backend.context,fd,read|write,&alias);
    if(result.alias!=0 || alias<0 || alias==fd)break;
    result.mapRX=backend.map(backend.context,fd,read|execute,&rx);
    if(result.mapRX!=0 || !rx || rx==reinterpret_cast<void*>(-1))break;
    result.mapRW=backend.map(backend.context,alias,read|write,&rw);
    if(result.mapRW!=0 || !rw || rw==reinterpret_cast<void*>(-1) || rw==rx)break;
    result.rxNotWritable=backend.protection(backend.context,rx,page,read|execute);
    result.rwNotExecutable=backend.protection(backend.context,rw,page,read|write);
    if(!result.rxNotWritable || !result.rwNotExecutable)break;
    // Only an owned x86-64 constant-return stub. Never a syscall or page code.
    unsigned char code[]={0xb8,42,0,0,0,0xc3};
    memcpy(rw,code,sizeof(code));synchronizeJitInstructions();
    result.sharedBytes=memcmp(rx,code,sizeof(code))==0;
    if(!result.sharedBytes)break;
    result.first=invokeOwnedJitStub(rx);
    code[1]=43;memcpy(rw,code,sizeof(code));synchronizeJitInstructions();
    if(memcmp(rx,code,sizeof(code))!=0)break;
    result.patched=invokeOwnedJitStub(rx);
    result.okay=result.first==42 && result.patched==43;
  } while(false);
  if(rw && rw!=reinterpret_cast<void*>(-1) && rw!=rx && backend.unmap(backend.context,rw,page)!=0)result.cleanup=false;
  if(rx && rx!=reinterpret_cast<void*>(-1) && backend.unmap(backend.context,rx,page)!=0)result.cleanup=false;
  if(alias>=0 && alias!=fd && backend.close(backend.context,alias)!=0)result.cleanup=false;
  if(fd>=0 && backend.close(backend.context,fd)!=0)result.cleanup=false;
  result.okay=result.okay && result.cleanup;
  return result;
}
bool probe_native_jit_memory();
bool prepare_native_jit_memory();
}
