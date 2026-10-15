#include "OrbisExecutableMemory.h"
#include <errno.h>
#include <pthread.h>
#include <string.h>
#include <unistd.h>
namespace orbisfox {
namespace {
OrbisJitBackend backend{};OrbisJitStats stats{};void* arena=nullptr;int descriptor=-1;bool mapped=false;
unsigned char permissions[jitArenaBytes/jitNativePage]{};
pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
struct Lock {Lock(){if(pthread_mutex_lock(&mutex))__builtin_trap();}~Lock(){if(pthread_mutex_unlock(&mutex))__builtin_trap();}};
[[noreturn]] void uncertain(){constexpr char message[]="Orbis JIT: uncertain shared-code ownership\n";(void)write(2,message,sizeof(message)-1);__builtin_trap();}
void cleanup(){
 if(mapped && backend.unmap(backend.user,arena,jitArenaBytes))uncertain();
 if(descriptor>=0 && backend.close(backend.user,descriptor))uncertain();
 arena=nullptr;descriptor=-1;mapped=false;stats.ready=stats.claimed=false;stats.reservedBytes=stats.committedBytes=0;memset(permissions,0,sizeof(permissions));
}
bool apply(void* address,size_t bytes,int protection){
 const int32_t rc=backend.protect(backend.user,address,bytes,protection);stats.lastResult=rc;
 if(rc)return false;
 if(!backend.query(backend.user,address,bytes,protection)){stats.lastResult=-1;return false;}
 return true;
}
void serialize(){
#if defined(__x86_64__)
 unsigned a=0,b=0,c=0,d=0;__asm__ volatile("cpuid":"+a"(a),"=b"(b),"=c"(c),"=d"(d)::"memory");
#endif
}
void writeStub(unsigned char value){
 unsigned char code[]={0xb8,value,0,0,0,0xc3};memcpy(static_cast<unsigned char*>(arena)+64,code,sizeof(code));serialize();
}
bool inArena(void* address,size_t bytes){
 const uintptr_t base=reinterpret_cast<uintptr_t>(arena),start=reinterpret_cast<uintptr_t>(address);
 return arena && bytes && start%jitNativePage==0 && bytes%jitNativePage==0 && start>=base && bytes<=jitArenaBytes && start-base<=jitArenaBytes-bytes;
}
}
bool prepare_orbis_executable_memory(const OrbisJitBackend& candidate){
 Lock lock;if(arena)return stats.ready;
 stats={};backend=candidate;stats.failedPhase=1;
 if(!backend.create||!backend.map||!backend.protect||!backend.query||!backend.unmap||!backend.close){stats.lastResult=-ENOSYS;return false;}
 stats.lastResult=backend.create(backend.user,jitArenaBytes,&descriptor);
 if(stats.lastResult || descriptor<0){descriptor=-1;return false;}
 stats.failedPhase=2;stats.lastResult=backend.map(backend.user,descriptor,&arena);
 if(stats.lastResult){arena=nullptr;cleanup();return false;}
 mapped=true;
 const uintptr_t base=reinterpret_cast<uintptr_t>(arena);
 if(!base || base%jitNativePage || base>(uintptr_t(1)<<47)-jitArenaBytes || !backend.query(backend.user,arena,jitArenaBytes,3)){
  stats.lastResult=-EINVAL;cleanup();return false;
 }
 stats.reservedBytes=jitArenaBytes;
 // Execute only our six-byte stub. Never execute while its page is writable.
 memset(arena,0,128);writeStub(42);stats.failedPhase=3;
 if(!apply(arena,jitNativePage,5)){cleanup();return false;}
 serialize();if(reinterpret_cast<int(*)()>(static_cast<unsigned char*>(arena)+64)()!=42){stats.lastResult=-1;cleanup();return false;}
 stats.failedPhase=4;if(!apply(arena,jitNativePage,3)){cleanup();return false;}
 writeStub(43);stats.failedPhase=5;
 if(!apply(arena,jitNativePage,5)){cleanup();return false;}
 serialize();if(reinterpret_cast<int(*)()>(static_cast<unsigned char*>(arena)+64)()!=43){stats.lastResult=-1;cleanup();return false;}
 stats.failedPhase=6;if(!apply(arena,jitArenaBytes,0)){cleanup();return false;}
 stats.ready=true;stats.failedPhase=0;return true;
}
void* reserve_orbis_executable_memory(size_t bytes){
 Lock lock;if(!stats.ready || stats.claimed || bytes!=jitArenaBytes){errno=ENOMEM;return nullptr;}
 stats.claimed=true;return arena;
}
bool protect_orbis_executable_memory(void* address,size_t bytes,int protection){
 Lock lock;
 if(!stats.ready || !stats.claimed || !inArena(address,bytes) || (protection!=0&&protection!=3&&protection!=5)){errno=EINVAL;return false;}
 if(!apply(address,bytes,protection))return false;
 const size_t first=(reinterpret_cast<uintptr_t>(address)-reinterpret_cast<uintptr_t>(arena))/jitNativePage;
 for(size_t i=first;i<first+bytes/jitNativePage;++i){
  if(permissions[i] && !protection)stats.committedBytes-=jitNativePage;
  else if(!permissions[i] && protection)stats.committedBytes+=jitNativePage;
  permissions[i]=static_cast<unsigned char>(protection);
 }
 return true;
}
void release_orbis_executable_memory(void* address,size_t bytes){
 Lock lock;if(address!=arena || bytes!=jitArenaBytes || !stats.claimed)uncertain();cleanup();
}
void shutdown_orbis_executable_memory(){Lock lock;if(stats.claimed)uncertain();cleanup();}
OrbisJitStats orbis_jit_memory_stats(){Lock lock;return stats;}
const char* orbis_jit_gate_reason(const OrbisJitStats& state){
 if(state.ready)return "owned-code-verified";
 if(state.lastResult==-ENOSYS)return "native-api-unavailable";
 if(state.failedPhase==1 && (state.lastResult==-EPERM || uint32_t(state.lastResult)==0x80020001u))return "shared-code-permission-denied";
 if(state.failedPhase==1)return "shared-code-allocation-failed";
 if(state.failedPhase==2)return "shared-code-mapping-or-query-failed";
 if(state.failedPhase)return "owned-code-or-wx-verification-failed";
 return "not-prepared";
}
}
