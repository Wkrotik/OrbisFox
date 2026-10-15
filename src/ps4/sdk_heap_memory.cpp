// Game direct memory backs only SDK-owned anonymous heap mappings. GC/file/
// shared mappings keep their real mmap semantics. No replacement allocator.
#include "orbisfox/sdk_heap_memory.h"
#include <stdint.h>
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
constexpr size_t page=16384;
// Public OpenOrbis ORBIS_KERNEL_WB_ONION=0: CPU write-back cached memory.
// WC_GARLIC=3 belongs to streaming graphics buffers, NOT pointer-heavy heaps.
constexpr int32_t cpuWriteBackMemoryType=0;
struct Mapping {void* address=nullptr;size_t bytes=0;off_t offset=0;};
Mapping maps[1024];bool enabled=false;SdkHeapMemoryStats stats;
pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
struct Lock {Lock(){if(pthread_mutex_lock(&mutex))__builtin_trap();}~Lock(){if(pthread_mutex_unlock(&mutex))__builtin_trap();}};
void error(int32_t rc){errno=int(uint32_t(rc)&0xffff);}
[[noreturn]] void ownershipFailure(){constexpr char text[]="SDK direct heap: uncertain physical-memory ownership; aborting\n";(void)write(2,text,sizeof(text)-1);__builtin_trap();}
bool overlap(const Mapping& m,uintptr_t address,size_t bytes){return m.address && bytes && address<=UINTPTR_MAX-bytes && reinterpret_cast<uintptr_t>(m.address)<address+bytes && address<reinterpret_cast<uintptr_t>(m.address)+m.bytes;}
}
void enable_sdk_direct_heap(bool value){Lock lock;enabled=value;}
void* map_sdk_direct_heap(size_t bytes,int protection){
 Lock lock;
 if(!enabled){errno=ENOTSUP;return reinterpret_cast<void*>(UINTPTR_MAX);}
 if(!bytes || bytes%page || protection!=3){errno=EINVAL;return reinterpret_cast<void*>(UINTPTR_MAX);}
 Mapping* slot=nullptr;for(auto& m:maps)if(!m.address){slot=&m;break;}
 if(!slot){errno=ENOMEM;return reinterpret_cast<void*>(UINTPTR_MAX);}
 const size_t limit=sceKernelGetDirectMemorySize();
 if(limit>size_t(INT64_MAX) || limit<bytes){++stats.allocationFailures;errno=ENOMEM;return reinterpret_cast<void*>(UINTPTR_MAX);}
 off_t offset=0;int32_t rc=sceKernelAllocateDirectMemory(0,off_t(limit),bytes,page,cpuWriteBackMemoryType,&offset);
 if(rc){++stats.allocationFailures;error(rc);return reinterpret_cast<void*>(UINTPTR_MAX);}
 void* memory=nullptr;rc=sceKernelMapDirectMemory(&memory,bytes,protection,0,offset,page);
 if(rc){++stats.mapFailures;if(sceKernelReleaseDirectMemory(offset,bytes))ownershipFailure();error(rc);return reinterpret_cast<void*>(UINTPTR_MAX);}
 if(!memory || reinterpret_cast<uintptr_t>(memory)%page || reinterpret_cast<uintptr_t>(memory)>UINTPTR_MAX-bytes)ownershipFailure();
 // SDK calloc legitimately assumes anonymous maps are zero-filled. Recycled
 // direct physical memory is not guaranteed zero: clear before publishing it.
 memset(memory,0,bytes);*slot={memory,bytes,offset};++stats.mappings;stats.bytes+=bytes;return memory;
}
int sdk_direct_heap_ownership(void* address,size_t bytes){Lock lock;for(const auto& m:maps){if(m.address==address && m.bytes==bytes)return 1;if(overlap(m,reinterpret_cast<uintptr_t>(address),bytes))return 2;}return 0;}
int unmap_sdk_direct_heap(void* address,size_t bytes){
 Lock lock;
 for(auto& m:maps)if(m.address==address && m.bytes==bytes){
  int32_t rc=sceKernelMunmap(address,bytes);if(rc){error(rc);return -1;}
  if(sceKernelReleaseDirectMemory(m.offset,m.bytes))ownershipFailure();
  --stats.mappings;stats.bytes-=m.bytes;m={};return 0;
 }
 errno=EINVAL;return -1;
}
SdkHeapMemoryStats sdk_direct_heap_stats(){Lock lock;return stats;}
}
