#include "OrbisGCChunkMemory.h"
#include <errno.h>
#include <pthread.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>
extern "C" size_t sceKernelGetDirectMemorySize();
extern "C" int32_t sceKernelAllocateDirectMemory(off_t,off_t,size_t,size_t,int32_t,off_t*);
extern "C" int32_t sceKernelMapDirectMemory(void**,size_t,int32_t,int32_t,off_t,size_t);
extern "C" int32_t sceKernelMunmap(void*,size_t);
extern "C" int32_t sceKernelReleaseDirectMemory(off_t,size_t);
namespace orbisfox {
namespace {
constexpr size_t chunk=1024*1024;
struct Mapping {void* address=nullptr;off_t physical=0;};
Mapping mappings[2048];GCChunkMemoryStats stats{};
pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
struct Lock {Lock(){if(pthread_mutex_lock(&mutex))__builtin_trap();}~Lock(){if(pthread_mutex_unlock(&mutex))__builtin_trap();}};
[[noreturn]] void uncertain(){constexpr char message[]="Orbis GC chunk: uncertain direct-memory ownership\n";(void)write(2,message,sizeof(message)-1);__builtin_trap();}
void error(int32_t result){errno=int(uint32_t(result)&0xffff);}
}
void* map_gc_chunk_memory(size_t bytes,size_t alignment){
 Lock lock;
 if(bytes!=chunk || alignment!=chunk){errno=EINVAL;return nullptr;}
 Mapping* slot=nullptr;for(auto& m:mappings)if(!m.address){slot=&m;break;}
 if(!slot){errno=ENOMEM;++stats.allocationFailures;return nullptr;}
 const size_t limit=sceKernelGetDirectMemorySize();
 if(limit>size_t(INT64_MAX) || limit<bytes){errno=ENOMEM;++stats.allocationFailures;return nullptr;}
 off_t physical=0;
 // CPU write-back Onion (public OpenOrbis value0), not graphics WC Garlic.
 int32_t rc=sceKernelAllocateDirectMemory(0,off_t(limit),bytes,alignment,0,&physical);
 if(rc){error(rc);++stats.allocationFailures;return nullptr;}
 void* address=nullptr;rc=sceKernelMapDirectMemory(&address,bytes,3,0,physical,alignment);
 if(rc){if(sceKernelReleaseDirectMemory(physical,bytes))uncertain();error(rc);++stats.mapFailures;return nullptr;}
 const uintptr_t base=reinterpret_cast<uintptr_t>(address);
 // SpiderMonkey encodes pointers in47bits. Never publish an incompatible map.
 if(!base || base%alignment || base>UINTPTR_MAX-bytes || base+bytes>(uintptr_t(1)<<47)){
  if(sceKernelMunmap(address,bytes) || sceKernelReleaseDirectMemory(physical,bytes))uncertain();
  errno=EINVAL;++stats.mapFailures;return nullptr;
 }
 memset(address,0,bytes);*slot={address,physical};++stats.mappings;stats.bytes+=bytes;return address;
}
bool unmap_gc_chunk_memory(void* address,size_t bytes){
 Lock lock;const uintptr_t base=reinterpret_cast<uintptr_t>(address);
 for(auto& m:mappings)if(m.address){
  const uintptr_t start=reinterpret_cast<uintptr_t>(m.address);
  if(m.address==address && bytes==chunk){
   if(sceKernelMunmap(address,bytes) || sceKernelReleaseDirectMemory(m.physical,bytes))uncertain();
   m={};--stats.mappings;stats.bytes-=bytes;return true;
  }
  if(bytes && base<=UINTPTR_MAX-bytes && start<base+bytes && base<start+chunk)uncertain();
 }
 return false;
}
GCChunkMemoryStats gc_chunk_memory_stats(){Lock lock;return stats;}
}
