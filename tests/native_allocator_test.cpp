#include "orbisfox/native_allocator.h"
#include "orbisfox/heap_reclaim_probe.h"
#include <pthread.h>
#include <atomic>
#include <cassert>
#include <cstring>
#include <cerrno>
#include <stdint.h>
#include <stddef.h>
#include <initializer_list>
#include <cstdlib>
#include <cstdio>
#include <unistd.h>
#ifdef SDK_TEST_NESTED_LINK
#define SDK_ORIGINAL(name) __real_sdk_##name
#else
#define SDK_ORIGINAL(name) sdk_##name
#endif
extern "C" {
void* SDK_ORIGINAL(malloc)(size_t);void SDK_ORIGINAL(free)(void*);void* SDK_ORIGINAL(realloc)(void*,size_t);void* SDK_ORIGINAL(calloc)(size_t,size_t);
void* SDK_ORIGINAL(aligned_alloc)(size_t,size_t);int SDK_ORIGINAL(posix_memalign)(void**,size_t,size_t);void* SDK_ORIGINAL(__memalign)(size_t,size_t);
void* SDK_ORIGINAL(valloc)(size_t);size_t SDK_ORIGINAL(malloc_usable_size)(void*);
void sdk_test_thread_flag(int);
void* __wrap_malloc(size_t);void __wrap_free(void*);void* __wrap_realloc(void*,size_t);void* __wrap_calloc(size_t,size_t);
void* __wrap_aligned_alloc(size_t,size_t);int __wrap_posix_memalign(void**,size_t,size_t);void* __wrap_memalign(size_t,size_t);
void* __wrap___memalign(size_t,size_t);void* __wrap_valloc(size_t);size_t __wrap_malloc_usable_size(void*);
}
std::atomic<unsigned> live{0};std::atomic<size_t> alignedRequest{0};thread_local unsigned nesting=0;
struct RealEntry {RealEntry(){if(nesting++==0)assert(live.fetch_add(1)==0);}~RealEntry(){if(--nesting==0)assert(live.fetch_sub(1)==1);}};
#define BACKEND(result,name,params,args) extern "C" result __real_##name params {RealEntry entry;return SDK_ORIGINAL(name) args;}
BACKEND(void*,malloc,(size_t n),(n))
BACKEND(void*,realloc,(void* p,size_t n),(p,n))
BACKEND(void*,calloc,(size_t n,size_t s),(n,s))
extern "C" void* __real_aligned_alloc(size_t a,size_t n){RealEntry entry;alignedRequest.store(n);return SDK_ORIGINAL(aligned_alloc)(a,n);}
BACKEND(void*,valloc,(size_t n),(n))
BACKEND(size_t,malloc_usable_size,(void* p),(p))
BACKEND(void*,__memalign,(size_t a,size_t n),(a,n))
extern "C" void* __real_memalign(size_t a,size_t n){RealEntry entry;return SDK_ORIGINAL(__memalign)(a,n);}
extern "C" int __real_posix_memalign(void** p,size_t a,size_t n){
  RealEntry entry;
  // Explicit nested public-entry call verifies recursive ownership.
  void* scratch=__wrap_malloc(48);assert(scratch);__wrap_free(scratch);
  return SDK_ORIGINAL(posix_memalign)(p,a,n);
}
extern "C" void __real_free(void* p){RealEntry entry;SDK_ORIGINAL(free)(p);}
struct Round {std::atomic<bool> start{false};std::atomic<void*> slots[8]{};};
struct Worker {Round* round;unsigned index;};
void* worker(void* opaque){
  auto& w=*static_cast<Worker*>(opaque);while(!w.round->start.load())__asm__ volatile("pause");
  for(unsigned i=0;i<512;++i){
    const size_t size=1+(i*73+w.index*31)%8192;const unsigned char pattern=static_cast<unsigned char>(w.index*17+i);
    auto* p=static_cast<unsigned char*>(__wrap_malloc(size));assert(p);memset(p,pattern,size);assert(__wrap_malloc_usable_size(p)>=size);
    p=static_cast<unsigned char*>(__wrap_realloc(p,size+103));assert(p);for(size_t j=0;j<size;++j)assert(p[j]==pattern);memset(p+size,pattern,103);__wrap_free(p);
    p=static_cast<unsigned char*>(__wrap_calloc(size,1));assert(p);for(size_t j=0;j<size;++j)assert(p[j]==0);__wrap_free(p);
    if(i%8==0){void* aligned=nullptr;assert(__wrap_posix_memalign(&aligned,64,size)==0);assert(reinterpret_cast<uintptr_t>(aligned)%64==0);__wrap_free(aligned);}
    if(i%64==0){
      // Include the last bin-sized request as well as mmap requests. Use the
      // same canaries and failure cleanup as the native startup workers.
      assert(orbisfox::probe_heap_boundary(__wrap_malloc,__wrap_calloc,
        __wrap_realloc,__wrap_free,i%3,pattern)==0);
    }
  }
  auto* transfer=static_cast<unsigned char*>(__wrap_malloc(1024));assert(transfer);memset(transfer,w.index,1024);w.round->slots[w.index].store(transfer);
  void* incoming=nullptr;const unsigned from=(w.index+7)%8;
  while(!(incoming=w.round->slots[from].exchange(nullptr)))__asm__ volatile("pause");
  for(unsigned j=0;j<1024;++j)assert(static_cast<unsigned char*>(incoming)[j]==from);__wrap_free(incoming);return nullptr;
}
#ifdef ORBISFOX_INSTALLED_SDK_OBJECTS
extern "C" void sdk_test_memory_primitives();
extern "C" void sdk_test_reclaim_observed();
extern "C" void sdk_test_advice_gate();
#endif
int main(){
#ifdef ORBISFOX_INSTALLED_SDK_OBJECTS
  sdk_test_memory_primitives();
#endif
  assert(orbisfox::initialize_native_allocator_lock());
  sdk_test_thread_flag(std::getenv("SDK_TEST_BIN_LOCKS")?1:0); // Explicit host model only; never native __libc writes.
#ifdef ORBISFOX_INSTALLED_SDK_OBJECTS
  sdk_test_advice_gate();
#endif
  // Exact0.51 crash class: mmap-backed262144 -> above-page50201 shrink.
  // With mremap unavailable the unmodified SDK copied278496 bytes into a
  // roughly50KiB destination. Guarded old tests ending at127 missed this.
  printf("SDK mapped shrink exact regression: begin262144->50201\n");fflush(stdout);
  auto* mapped=static_cast<unsigned char*>(__wrap_malloc(262144));assert(mapped);
  memset(mapped,0x5d,262144);
  auto* medium=static_cast<unsigned char*>(__wrap_realloc(mapped,50201));assert(medium);
  for(size_t i=0;i<50201;++i)assert(medium[i]==0x5d);
  __wrap_free(medium);
  if(getenv("SDK_TEST_ONLY_MAPPED_SHRINK"))return 0;
  const auto reclaim=orbisfox::probe_heap_reclaim(__wrap_malloc,__wrap_calloc,__wrap_realloc,__wrap_free,[](unsigned){});
  std::fprintf(stderr,"SDK reclaim canaries: completed=%u/32 adjacent-four-chunk-groups=%u error-mask=0x%x public-calls=%llu; raw before guards, not firmware proof\n",reclaim.completed,reclaim.adjacentGroups,reclaim.errorMask,static_cast<unsigned long long>(reclaim.calls));
  assert(reclaim.okay());
#ifdef ORBISFOX_INSTALLED_SDK_OBJECTS
  sdk_test_reclaim_observed();
  assert(orbisfox::native_allocator_audited_arena_count()>0);
#endif
  // Host-only read of the audited musl64 chunk header, before guard mode.
  // Prove actual bin/mmap path selection; requested sizes alone are not proof.
  for(unsigned sample=0;sample<3;++sample){
    const size_t size=orbisfox::heap_boundary_request(sample);
    auto* p=static_cast<unsigned char*>(__wrap_malloc(size));assert(p);
    size_t csize=0;memcpy(&csize,p-sizeof(size_t),sizeof(csize));
    assert(bool(csize&1)==(sample==0)); // C_INUSE set for bin, clear for mmap.
    assert(__wrap_malloc_usable_size(p)>=size);__wrap_free(p);
    assert(orbisfox::probe_heap_boundary(__wrap_malloc,__wrap_calloc,
      __wrap_realloc,__wrap_free,sample,0x5c)==0);
  }
  std::fprintf(stderr,"SDK boundary paths: request229360=bin, request229361/229376=mmap; actual raw chunk headers, before guards, not firmware proof\n");
#ifdef ORBISFOX_INSTALLED_SDK_OBJECTS
  orbisfox::configure_native_allocator_bin_audit(false);
#endif
  const bool guarded=std::getenv("SDK_TEST_HEAP_GUARDS")!=nullptr;
  FILE* trace=guarded?std::tmpfile():nullptr;
  if(guarded){assert(trace);assert(orbisfox::configure_native_allocator_diagnostics(fileno(trace)));}
  for(unsigned cycle=0;cycle<(guarded?2u:32u);++cycle){
    Round round;Worker workers[8];pthread_t threads[8];const auto before=orbisfox::native_allocator_entry_count();
    for(unsigned i=0;i<8;++i){workers[i]={&round,i};assert(!pthread_create(&threads[i],nullptr,worker,&workers[i]));}
    round.start=true;for(auto thread:threads)assert(!pthread_join(thread,nullptr));
    for(auto& slot:round.slots)assert(slot.load()==nullptr);
    assert(live.load()==0&&orbisfox::native_allocator_entry_count()-before>8*512*5);
    for(auto alloc:{__wrap_aligned_alloc,__wrap_memalign,__wrap___memalign}){void* p=alloc(64,128);assert(p&&reinterpret_cast<uintptr_t>(p)%64==0);__wrap_free(p);}
    void* mismatched=__wrap_aligned_alloc(64,73);assert(alignedRequest.load()==73);__wrap_free(mismatched);
    void* posix=nullptr;errno=EAGAIN;assert(__wrap_posix_memalign(&posix,64,73)==0);assert(errno==EAGAIN);__wrap_free(posix);
    void* p=__wrap_valloc(128);assert(p&&reinterpret_cast<uintptr_t>(p)%4096==0);__wrap_free(p);__wrap_free(nullptr);
    assert(__wrap_malloc(SIZE_MAX)==nullptr);assert(__wrap_calloc(SIZE_MAX,2)==nullptr);
    p=__wrap_malloc(64);assert(p);memset(p,17,64);assert(!__wrap_realloc(p,SIZE_MAX));for(unsigned i=0;i<64;++i)assert(static_cast<unsigned char*>(p)[i]==17);__wrap_free(p);
    void* output=reinterpret_cast<void*>(1);assert(__wrap_posix_memalign(&output,3,128)!=0);assert(output==reinterpret_cast<void*>(1));
    assert(orbisfox::checkpoint_native_allocator_diagnostics());
  }
  // Trace fd intentionally survives until process exit, matching destructor
  // lifetime on PS4. No stale closed-fd access from late wrapped deallocation.
}
