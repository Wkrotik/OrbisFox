#ifdef ORBISFOX_FULL_GECKO
#include "orbisfox/native_allocator.h"
#include "orbisfox/heap_expand_fallback.h"
#include <sys/types.h>
#ifdef ORBISFOX_NATIVE_DIRECT_HEAP
#include "orbisfox/sdk_heap_memory.h"
extern "C" void* __real___mmap(void*,size_t,int,int,int,off_t);
#endif
#ifdef ORBISFOX_NATIVE_RUN_LOGS
#include "orbisfox/run_logs.h"
#endif
#include "orbisfox/heap_diagnostics.h"
#ifdef ORBISFOX_SDK_BIN_AUDIT
#include "orbisfox/heap_bin_audit.h"
// SDK-owned state is mutable; only our accessor view is read-only. Declaring
// the actual global const would give optimizers an invalid immutability promise.
extern "C" unsigned char orbisfox_sdk_malloc_state[];
extern "C" void* __real___expand_heap(size_t*);
extern "C" void* __mmap(void*,size_t,int,int,int,off_t);
#ifndef ORBISFOX_INSTALLED_SDK_OBJECTS
// Public OpenOrbis declaration encodes the native sizeOut pointer as size_t.
extern "C" int32_t sceKernelAvailableFlexibleMemorySize(size_t);
#endif
extern "C" int __real___madvise(void*,size_t,int);
extern "C" int __real___munmap(void*,size_t);
#ifdef ORBISFOX_INSTALLED_SDK_OBJECTS
extern "C" void* sdk_memcpy(void*,const void*,size_t);
#endif
#endif
#include <pthread.h>
#include <atomic>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
extern "C" {
void* __real_malloc(size_t);void* __real_calloc(size_t,size_t);void* __real_realloc(void*,size_t);void __real_free(void*);
void* __real_aligned_alloc(size_t,size_t);int __real_posix_memalign(void**,size_t,size_t);
void* __real_memalign(size_t,size_t);void* __real___memalign(size_t,size_t);void* __real_valloc(size_t);size_t __real_malloc_usable_size(void*);
}
namespace {
// Constant initialization is usable by compiler-emitted constructors. Native
// mutex APIs do not allocate through the application heap. Never call stdio
// under this lock: stream->heap remains the only allowed lock ordering.
std::atomic<unsigned> state{0};std::atomic<uint64_t> entries{0};
pthread_mutex_t mutex{};int initResult=-1;unsigned depth=0;uint64_t reallocCopyClamps=0;
int traceFD=-1;bool traceFailure=false;
uint64_t saturationRequests=0,untrackedReturns=0;
orbisfox::HeapDiagnostics<262144,512,8*1024*1024> diagnostics;
static_assert(sizeof(orbisfox::HeapDiagnosticEvent)==64);
void require(bool okay){
  if(okay)return;
  static const char text[]="OrbisFox: native heap mutex operation failed\n";
  write(STDERR_FILENO,text,sizeof(text)-1);__builtin_trap();
}
void initialize(){
  pthread_mutexattr_t attr{};int rc=pthread_mutexattr_init(&attr);
  if(rc){initResult=rc;return;}
  rc=pthread_mutexattr_settype(&attr,PTHREAD_MUTEX_RECURSIVE);
  if(!rc)rc=pthread_mutex_init(&mutex,&attr);
  const int destroy=pthread_mutexattr_destroy(&attr);initResult=rc?rc:destroy;
}
#ifdef ORBISFOX_SDK_BIN_AUDIT
orbisfox::HeapBinAudit binAudit;
const char* lastGoodOperation="none",*lastGoodPhase="none";uintptr_t lastGoodCaller=0;
bool allApiAudit=true,reclaimVerified=false;
struct ReallocContext {bool active=false;uintptr_t input=0,output=0;size_t bytes=0;} reallocContext;
struct LeafContext {uintptr_t first=0,second=0;size_t bytes=0;} leafContext;
struct Endpoint {uintptr_t head=0,tail=0;uint64_t headSize=0,tailSize=0;};
Endpoint beforeRealloc[64]{},beforeLeaf[64]{};bool reallocSnapshot=false,leafSnapshot=false;
void snapshotEndpoints(Endpoint (&out)[64]){
  for(unsigned i=0;i<64;++i){
    memcpy(&out[i].head,orbisfox_sdk_malloc_state+16+24*i,8);memcpy(&out[i].tail,orbisfox_sdk_malloc_state+24+24*i,8);
    uint64_t words[4]{};out[i].headSize=binAudit.describe(out[i].head,words)?words[1]:0;
    out[i].tailSize=binAudit.describe(out[i].tail,words)?words[1]:0;
  }
}
void auditBins(const char* operation,uintptr_t site,const char* phase){
  const auto failure=binAudit.check(orbisfox_sdk_malloc_state);
  if(!failure.code){lastGoodOperation=operation;lastGoodCaller=site;lastGoodPhase=phase;return;}
  // No stdio, allocation, pointer repair or private-state mutation on failure.
  char text[1024];size_t n=0;
  const auto append=[&](const char* p){while(*p && n<sizeof(text)-1)text[n++]=*p++;};
  const auto hex=[&](uint64_t value){append("0x");for(int s=60;s>=0;s-=4)if(n<sizeof(text)-1)text[n++]="0123456789abcdef"[(value>>s)&15];};
  append("ORBISFOX SDK BIN AUDIT: phase=");append(phase);append(" api=");append(operation);
  append(" caller=");hex(site);append(" code=");hex(failure.code);append(" bin=");hex(failure.bin);
  append(" chunk=");hex(failure.chunk);append(" actual=");hex(failure.actual);append(" expected=");hex(failure.expected);
  uint64_t header[4];if(binAudit.describe(failure.chunk,header)){
    append(" psize=");hex(header[0]);append(" csize=");hex(header[1]);append(" next=");hex(header[2]);append(" prev=");hex(header[3]);
  }
  if(reallocContext.active){append(" realloc-in=");hex(reallocContext.input);append(" realloc-bytes=");hex(reallocContext.bytes);append(" realloc-out=");hex(reallocContext.output);}
  append(" leaf-first=");hex(leafContext.first);append(" leaf-second=");hex(leafContext.second);append(" leaf-bytes=");hex(leafContext.bytes);
  if(failure.bin<64){
    if(reallocSnapshot){append(" realloc-before-head=");hex(beforeRealloc[failure.bin].head);append(" realloc-before-head-size=");hex(beforeRealloc[failure.bin].headSize);append(" realloc-before-tail=");hex(beforeRealloc[failure.bin].tail);append(" realloc-before-tail-size=");hex(beforeRealloc[failure.bin].tailSize);}
    if(leafSnapshot){append(" leaf-before-head=");hex(beforeLeaf[failure.bin].head);append(" leaf-before-head-size=");hex(beforeLeaf[failure.bin].headSize);append(" leaf-before-tail=");hex(beforeLeaf[failure.bin].tail);append(" leaf-before-tail-size=");hex(beforeLeaf[failure.bin].tailSize);}
  }
  append(" last-good-api=");append(lastGoodOperation);append(" last-good-caller=");hex(lastGoodCaller);append(" last-good-phase=");append(lastGoodPhase);append("\n");
#ifdef ORBISFOX_NATIVE_RUN_LOGS
  orbisfox::native_write_heap_audit(text,n);
#endif
  write(STDERR_FILENO,text,n);__builtin_trap();
}
#endif
struct HeapLock {
  const char* operation;uintptr_t site;
  HeapLock(const char* name="internal",uintptr_t address=0,void* input=nullptr,size_t bytes=0):operation(name),site(address){
    (void)input;(void)bytes;
    require(orbisfox::initialize_native_allocator_lock());require(pthread_mutex_lock(&mutex)==0);++depth;entries.fetch_add(1,std::memory_order_relaxed);
#ifdef ORBISFOX_SDK_BIN_AUDIT
    if(depth==1){
      reallocContext={operation[0]=='r',reinterpret_cast<uintptr_t>(input),0,bytes};leafContext={};reallocSnapshot=leafSnapshot=false;
      if(allApiAudit || reallocContext.active)auditBins(operation,site,"before");
      if(reallocContext.active){snapshotEndpoints(beforeRealloc);reallocSnapshot=true;}
    }
#endif
  }
  ~HeapLock(){
#ifdef ORBISFOX_SDK_BIN_AUDIT
    if(depth==1){
      if(allApiAudit || reallocContext.active)auditBins(operation,site,"after");
      reallocContext.active=false;
    }
#endif
    --depth;require(pthread_mutex_unlock(&mutex)==0);
  }
};
bool guarded(){return diagnostics.enabled()&&depth==1;}
void record(const orbisfox::HeapDiagnosticEvent& e){
  if(traceFD<0)return;const int saved=errno;
  const off_t at=64+off_t((e.sequence-1)%4096)*sizeof(e);
  if(pwrite(traceFD,&e,sizeof(e),at)!=ssize_t(sizeof(e)))traceFailure=true;
  if(e.operation==10){
    if(!saturationRequests){
      static const char text[]="OrbisFox: heap tracking saturated; new allocations use raw SDK pointers without guards, existing guarded ownership retained\n";
      write(STDERR_FILENO,text,sizeof(text)-1);
    }
    ++saturationRequests;
  }
  if(e.operation==11&&e.pointer)++untrackedReturns;
  // One header update preserves the latest event plus explicit coverage census.
  // Occupancy is sampled at callback time (before some release/eviction commits).
  const uint64_t snapshot[4]={e.sequence,
    uint64_t(diagnostics.active()+diagnostics.quarantined())|(uint64_t(diagnostics.trackingLimit())<<32),
    saturationRequests,untrackedReturns};
  if(pwrite(traceFD,snapshot,sizeof(snapshot),32)!=ssize_t(sizeof(snapshot)))traceFailure=true;
  errno=saved;
}
void fault(const char* message,const orbisfox::HeapDiagnosticEvent& e){
  char text[768];size_t n=0;
  const auto append=[&](const char* value){while(*value&&n<sizeof(text)-1)text[n++]=*value++;};
  const auto hex=[&](uint64_t value){append("0x");for(int shift=60;shift>=0;shift-=4)if(n<sizeof(text)-1)text[n++]="0123456789abcdef"[(value>>shift)&15];};
  append("ORBISFOX HEAP DIAGNOSTIC: ");append(message);append(" ptr=");hex(e.pointer);append(" bytes=");hex(e.size);
  append(" detected-at=");hex(e.caller);append(" allocated-at=");hex(e.allocatedAt);append(" freed-at=");hex(e.freedAt);
  append(traceFailure?" trace-IO-error=1\n":" trace-IO-error=0\n");
#ifdef ORBISFOX_NATIVE_RUN_LOGS
  orbisfox::native_write_heap_audit(text,n);
#endif
  write(STDERR_FILENO,text,n);if(traceFD>=0)pwrite(traceFD,text,n,64+4096*sizeof(e));
  __builtin_trap(); // Real detected corruption, never a fake successful free.
}
bool powerAlignment(size_t a){return a&&!(a&(a-1));}
uintptr_t caller(void* address){return reinterpret_cast<uintptr_t>(address);}
}
namespace orbisfox {
bool initialize_native_allocator_lock(){
  unsigned expected=0;
  if(state.compare_exchange_strong(expected,1)){initialize();state.store(2,std::memory_order_release);}
  else while(state.load(std::memory_order_acquire)==1)__asm__ volatile("pause");
  return initResult==0;
}
uint64_t native_allocator_entry_count(){return entries.load(std::memory_order_relaxed);}
uint64_t native_allocator_realloc_copy_fix_count(){HeapLock lock;return reallocCopyClamps;}
#ifdef ORBISFOX_SDK_BIN_AUDIT
size_t native_allocator_audited_arena_count(){HeapLock lock;return binAudit.arenaCount();}
void configure_native_allocator_reclaim(bool verified){HeapLock lock;reclaimVerified=verified;}
void configure_native_allocator_bin_audit(bool allCalls){HeapLock lock;allApiAudit=allCalls;}
#endif
bool configure_native_allocator_diagnostics(int fd){
  HeapLock lock;if(fd<0||diagnostics.enabled())return false;
  // Format:64-byte LE header;4096 circular64-byte events; optional ASCII fault.
  uint64_t header[8]={UINT64_C(0x504145484658424f),2,64,4096,0,uint64_t(diagnostics.trackingLimit())<<32,0,0};
  if(pwrite(fd,header,sizeof(header),0)!=ssize_t(sizeof(header)))return false;
  traceFD=fd;traceFailure=false;saturationRequests=0;untrackedReturns=0;
  return diagnostics.enable({__real_malloc,__real_free,record,fault});
}
bool checkpoint_native_allocator_diagnostics(){
  HeapLock lock;return !diagnostics.enabled()||(diagnostics.drain(reinterpret_cast<uintptr_t>(__builtin_return_address(0)))&&!traceFailure);
}
}
#ifdef ORBISFOX_SDK_BIN_AUDIT
extern "C" void* __wrap___expand_heap(size_t* size){
  HeapLock lock("__expand_heap",reinterpret_cast<uintptr_t>(__builtin_return_address(0)));
  const size_t requested=*size;bool retried=false;
  void* p=nullptr;
#ifdef ORBISFOX_NATIVE_DIRECT_HEAP
  const size_t arena=(*size+16383)&~size_t(16383);
  if(arena>=*size){
    void* direct=orbisfox::map_sdk_direct_heap(arena<4*1024*1024?4*1024*1024:arena,3);
    if(direct && direct!=reinterpret_cast<void*>(UINTPTR_MAX)){p=direct;*size=arena<4*1024*1024?4*1024*1024:arena;}
  }
#endif
  if(!p)p=orbisfox::expand_heap_with_retry(size,__real___expand_heap,[&](size_t bytes){
    retried=true;return __mmap(nullptr,bytes,3,0x1002,-1,0);
  });
  if(p)require(binAudit.addArena(p,*size));
  if(retried){
    const int saved=errno;size_t available=0;int32_t query=-1;
#ifndef ORBISFOX_INSTALLED_SDK_OBJECTS
    query=sceKernelAvailableFlexibleMemorySize(reinterpret_cast<size_t>(&available));
#endif
    char text[256];size_t used=0;
    auto append=[&](const char* s){while(*s&&used<sizeof(text))text[used++]=*s++;};
    auto hex=[&](uint64_t value){static const char digits[]="0123456789abcdef";append("0x");for(int bit=60;bit>=0;bit-=4){if(used<sizeof(text))text[used++]=digits[(value>>bit)&15];}};
    append("SDK ARENA RETRY: request=");hex(requested);append(" mapped=");hex(p?*size:0);append(" errno=");hex(saved);append(" flexible-rc=");hex(uint32_t(query));append(" flexible-available-MiB-rounded=");hex(available);append("\n");
#ifdef ORBISFOX_NATIVE_RUN_LOGS
    orbisfox::native_write_heap_audit(text,used);
#endif
    (void)write(STDERR_FILENO,text,used);errno=saved;
  }
  return p;
}
// SDK free-page discard is optional. Until an isolated native retention probe
// proves its range contract, return a real unsupported error, not fake success.
extern "C" int __wrap___madvise(void* address,size_t bytes,int advice){
  HeapLock lock("SDK-discard",reinterpret_cast<uintptr_t>(__builtin_return_address(0)));
  const int saved=errno;
  leafContext={reinterpret_cast<uintptr_t>(address),static_cast<uintptr_t>(advice),bytes};
  leafSnapshot=false;auditBins("SDK-discard",lock.site,"discard-before");
  snapshotEndpoints(beforeLeaf);leafSnapshot=true;
#ifdef ORBISFOX_NATIVE_DIRECT_HEAP
  if(orbisfox::sdk_direct_heap_ownership(address,bytes)){errno=ENOTSUP;return -1;}
#endif
  if(!reclaimVerified){errno=ENOTSUP;return -1;}
  const int rc=__real___madvise(address,bytes,advice),failure=errno;
  auditBins("SDK-discard",lock.site,"discard-after");
  errno=rc?failure:saved;return rc;
}
extern "C" int __wrap___munmap(void* address,size_t bytes){
  HeapLock lock("SDK-unmap",reinterpret_cast<uintptr_t>(__builtin_return_address(0)));
  leafContext={reinterpret_cast<uintptr_t>(address),0,bytes};
  leafSnapshot=false;auditBins("SDK-unmap",lock.site,"unmap-before");
  snapshotEndpoints(beforeLeaf);leafSnapshot=true;
  int rc;
#ifdef ORBISFOX_NATIVE_DIRECT_HEAP
  const int owner=orbisfox::sdk_direct_heap_ownership(address,bytes);
  if(owner==2){errno=EINVAL;rc=-1;}
  else if(owner==1)rc=orbisfox::unmap_sdk_direct_heap(address,bytes);
  else rc=__real___munmap(address,bytes);
#else
  rc=__real___munmap(address,bytes);
#endif
  const int failure=errno;
  auditBins("SDK-unmap",lock.site,"unmap-after");errno=failure;return rc;
}
#ifdef ORBISFOX_NATIVE_DIRECT_HEAP
extern "C" void* __wrap___mmap(void* desired,size_t bytes,int protection,int flags,int fd,off_t offset){
  HeapLock lock("SDK-map",reinterpret_cast<uintptr_t>(__builtin_return_address(0)));
  if(!desired && flags==0x1002 && protection==3 && fd==-1 && !offset && bytes && !(bytes%16384)){
    void* p=orbisfox::map_sdk_direct_heap(bytes,protection);
    if(p && p!=reinterpret_cast<void*>(UINTPTR_MAX))return p;
  }
  return __real___mmap(desired,bytes,protection,flags,fd,offset);
}
#endif
#endif
#if defined(ORBISFOX_SDK_BIN_AUDIT) || defined(ORBISFOX_SDK_REALLOC_COMPAT)
// Only SDK realloc's private copy reference targets this bridge. Its ENOSYS
// mremap fallback incorrectly copies OLD usable bytes even when shrinking.
// Bound writes by the NEW genuine SDK allocation, including guarded/nested
// backend calls whose allocation capacity differs from the public request.
extern "C" void* orbisfox_sdk_realloc_copy(void* destination,const void* source,size_t bytes){
  HeapLock lock("SDK-copy",reinterpret_cast<uintptr_t>(__builtin_return_address(0)));
#ifdef ORBISFOX_SDK_BIN_AUDIT
  leafContext={reinterpret_cast<uintptr_t>(destination),reinterpret_cast<uintptr_t>(source),bytes};
  leafSnapshot=false;auditBins("SDK-copy",lock.site,"copy-before");
  snapshotEndpoints(beforeLeaf);leafSnapshot=true;
#endif
  const size_t capacity=__real_malloc_usable_size(destination);
  if(!capacity && bytes)__builtin_trap();
  if(bytes>capacity){bytes=capacity;++reallocCopyClamps;}
#ifdef ORBISFOX_INSTALLED_SDK_OBJECTS
  void* result=sdk_memcpy(destination,source,bytes);
#else
  void* result=memcpy(destination,source,bytes);
#endif
#ifdef ORBISFOX_SDK_BIN_AUDIT
  auditBins("SDK-copy",lock.site,"copy-after");
#endif
  return result;
}
#endif
// The genuine SDK allocator remains the single owner. Never write __libc flags.
// Diagnostics apply only at the outer public API boundary. In particular, SDK
// memalign/realloc inspect real chunk metadata internally; nested wrapped SDK
// calls must receive raw pointers, not guarded user pointers.
extern "C" void* __wrap_malloc(size_t size){
  HeapLock lock("malloc",caller(__builtin_return_address(0)));if(!guarded())return __real_malloc(size);
  return diagnostics.allocate(size,16,caller(__builtin_return_address(0)),[](size_t n){return __real_malloc(n);});
}
extern "C" void* __wrap_calloc(size_t count,size_t size){
  HeapLock lock("calloc",caller(__builtin_return_address(0)));if(!guarded())return __real_calloc(count,size);
  if(count&&size>SIZE_MAX/count){errno=ENOMEM;return nullptr;}
  return diagnostics.allocate(count*size,16,caller(__builtin_return_address(0)),[](size_t n){return __real_calloc(1,n);});
}
extern "C" void* __wrap_realloc(void* pointer,size_t size){
  HeapLock lock("realloc",caller(__builtin_return_address(0)),pointer,size);if(!guarded()){
    void* result=__real_realloc(pointer,size);
#ifdef ORBISFOX_SDK_BIN_AUDIT
    if(depth==1)reallocContext.output=reinterpret_cast<uintptr_t>(result);
#endif
    return result;
  }
  return diagnostics.reallocate(pointer,size,caller(__builtin_return_address(0)),[](void* p,size_t n){return __real_realloc(p,n);});
}
extern "C" void __wrap_free(void* pointer){
  const int saved=errno;{HeapLock lock("free",caller(__builtin_return_address(0)));if(guarded())diagnostics.release(pointer,caller(__builtin_return_address(0)));else __real_free(pointer);}errno=saved;
}
extern "C" size_t __wrap_malloc_usable_size(void* pointer){
  HeapLock lock("malloc_usable_size",caller(__builtin_return_address(0)));if(!guarded())return __real_malloc_usable_size(pointer);
  return diagnostics.usable(pointer,caller(__builtin_return_address(0)),[](void* p){return __real_malloc_usable_size(p);});
}
#define ALIGNED(name) \
extern "C" void* __wrap_##name(size_t alignment,size_t size){ \
  HeapLock lock(#name,caller(__builtin_return_address(0)));if(!guarded()||!powerAlignment(alignment))return __real_##name(alignment,size); \
  return diagnostics.allocate(size,alignment,caller(__builtin_return_address(0)),[&](size_t n){return __real_##name(alignment,n);}); \
}
ALIGNED(memalign)
ALIGNED(__memalign)
#undef ALIGNED
extern "C" void* __wrap_aligned_alloc(size_t alignment,size_t size){
  HeapLock lock("aligned_alloc",caller(__builtin_return_address(0)));
  // Pass invalid requests unchanged to the genuine SDK. Diagnostic padding
  // must not conceal a size/alignment mismatch (SDK policy is not replaced).
  if(!guarded()||!powerAlignment(alignment)||size%alignment)return __real_aligned_alloc(alignment,size);
  return diagnostics.allocate(size,alignment,caller(__builtin_return_address(0)),[&](size_t n){return __real_aligned_alloc(alignment,n);});
}
extern "C" int __wrap_posix_memalign(void** pointer,size_t alignment,size_t size){
  HeapLock lock("posix_memalign",caller(__builtin_return_address(0)));if(!guarded()||!pointer||alignment<sizeof(void*)||!powerAlignment(alignment))return __real_posix_memalign(pointer,alignment,size);
  const int saved=errno;
  int result=0;void* user=diagnostics.allocate(size,alignment,caller(__builtin_return_address(0)),[&](size_t n){void* raw=nullptr;result=__real_posix_memalign(&raw,alignment,n);return result?nullptr:raw;});
  errno=saved;if(!user)return result?result:ENOMEM;*pointer=user;return 0;
}
extern "C" void* __wrap_valloc(size_t size){
  HeapLock lock("valloc",caller(__builtin_return_address(0)));if(!guarded())return __real_valloc(size);
  const int page=getpagesize();if(page<=0||!powerAlignment(size_t(page))){errno=EINVAL;return nullptr;}
  return diagnostics.allocate(size,size_t(page),caller(__builtin_return_address(0)),[](size_t n){return __real_valloc(n);});
}
#endif
