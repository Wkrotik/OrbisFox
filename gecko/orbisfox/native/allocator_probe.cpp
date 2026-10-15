#include "orbisfox/native_allocator.h"
#include "orbisfox/sdk_heap_memory.h"
#include "orbisfox/heap_reclaim_probe.h"
#include "orbisfox/heap_advice_probe.h"
#include "orbisfox/presenter.h"
#include <orbis/libkernel.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <atomic>
#include <stdint.h>
#include <unistd.h>
#include <sys/mman.h>
// Read-only diagnostic for the exact SDK archive audited at link time. This
// address is never used for locking or to enable SDK thread/futex machinery.
extern "C" unsigned char __libc[];
namespace orbisfox {
namespace {
struct State {std::atomic<bool> start{false},failed{false};std::atomic<void*> slots[8]{};int ids[8]{};unsigned errors[8]{},completed[8]{};};
struct Worker {State* state;unsigned index;};
struct Watchdog {std::atomic<bool> done{false};uint64_t deadline=0;};
void* watch(void* opaque){
  auto& guard=*static_cast<Watchdog*>(opaque);
  while(!guard.done.load()){
    if(sceKernelGetProcessTime()>=guard.deadline){
      constexpr char text[]="Native allocator startup probe: 30s deadline exceeded; terminating before live-worker stack teardown\n";
      write(STDERR_FILENO,text,sizeof(text)-1);__builtin_trap();
    }
    sceKernelUsleep(10000);
  }
  return nullptr;
}
void* work(void* opaque){
  auto& w=*static_cast<Worker*>(opaque);auto& s=*w.state;s.ids[w.index]=scePthreadGetthreadid();
  while(!s.start.load())sceKernelUsleep(100);
  const auto failure=[&](unsigned bit){s.failed=true;s.errors[w.index]|=bit;};
  for(unsigned i=0;i<512;++i){
    const size_t size=1+(i*73+w.index*31)%8192;const unsigned char value=static_cast<unsigned char>(w.index*17+i);
    auto* p=static_cast<unsigned char*>(malloc(size));
    if(!p){failure(1);continue;}memset(p,value,size);
    auto* grown=static_cast<unsigned char*>(realloc(p,size+103));
    if(!grown){free(p);failure(2);continue;}p=grown;
    for(size_t j=0;j<size;++j)if(p[j]!=value)failure(4);free(p);
    p=static_cast<unsigned char*>(calloc(size,1));if(!p){failure(8);continue;}
    for(size_t j=0;j<size;++j)if(p[j]!=0)failure(16);free(p);
    if(i%8==0){void* aligned=nullptr;if(posix_memalign(&aligned,64,size)!=0||!aligned)failure(32);
      else{if(reinterpret_cast<uintptr_t>(aligned)%64)failure(64);free(aligned);}}
    if(i%64==0){
      const unsigned boundary=probe_heap_boundary(malloc,calloc,realloc,free,i%3,value);
      if(boundary)failure(boundary<<9);
    }
    ++s.completed[w.index];
  }
  auto* transfer=static_cast<unsigned char*>(malloc(1024));
  if(transfer)memset(transfer,w.index,1024);else failure(128);
  // Non-null sentinel terminates the ring even after allocation failure.
  s.slots[w.index].store(transfer?transfer:reinterpret_cast<void*>(1));
  void* incoming=nullptr;const unsigned from=(w.index+7)%8;
  while(!(incoming=s.slots[from].exchange(nullptr)))sceKernelUsleep(100);
  if(incoming!=reinterpret_cast<void*>(1)){
    for(unsigned j=0;j<1024;++j)if(static_cast<unsigned char*>(incoming)[j]!=from)failure(256);free(incoming);
  }
  return nullptr;
}
}
bool probe_native_allocator(){
  if(!initialize_native_allocator_lock())return false;
  Watchdog guard;guard.deadline=sceKernelGetProcessTime()+30000000;
  pthread_t monitor{};const int created=pthread_create(&monitor,nullptr,watch,&guard);
  if(created!=0){log("Native allocator watchdog create=%d",created);return false;}
  const auto stopWatchdog=[&]{
    guard.done.store(true);const int rc=pthread_join(monitor,nullptr);
    if(rc!=0){log("Native allocator watchdog join=%d; aborting before uncertain stack teardown",rc);abort();}
  };
  const auto advice=probe_heap_advice(16384,
    [](size_t bytes){return mmap(nullptr,bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);},
    [](void* p,size_t bytes){return madvise(p,bytes,MADV_DONTNEED);},
    [](void* p,size_t bytes){return munmap(p,bytes);});
  configure_native_allocator_reclaim(advice.safe());
  log("SDK free-page discard retention gate: %s completed=%u/3 error-mask=0x%x span=%llu offset=%llu actual=0x%x expected=0x%x advice-rc=%d; real SDK ownership retained, rejected advice returns ENOTSUP, not fake success",advice.safe()?"SUPPORTED":"UNSUPPORTED",advice.completed,advice.errorMask,(unsigned long long)advice.failedSpan,(unsigned long long)advice.failedOffset,advice.actual,advice.expected,advice.adviceResult);
  if(advice.errorMask&16){stopWatchdog();return false;} // Never abandon an uncertain mapping owner.
  enable_sdk_direct_heap(true);
  log("SDK heap backing: game direct memory preferred; flexible memory retained for GC/shared/file mappings; unsupported direct discard returns ENOTSUP");
  log("Native allocator reclaim/coalesce/pretrim canaries: BEGIN before engine startup; real SDK backing, no guard mode");
  const uint64_t reclaimBefore=native_allocator_entry_count();
  const auto reclaim=probe_heap_reclaim(malloc,calloc,realloc,free,[](unsigned round){
    if(round%8==0)log("Native allocator reclaim canary round=%u/32",round);
  });
  const uint64_t reclaimCalls=native_allocator_entry_count()-reclaimBefore;
  const bool reclaimOkay=reclaim.okay() && reclaimCalls>=reclaim.calls;
  log("Native allocator reclaim/coalesce/pretrim canaries: %s completed=%u/32 adjacent-four-chunk-groups=%u error-mask=0x%x protected-entries=%llu expected-public-calls=%llu; observed adjacency, not internal-bin execution or website stability proof",reclaimOkay?"PASS":"FAIL",reclaim.completed,reclaim.adjacentGroups,reclaim.errorMask,(unsigned long long)reclaimCalls,(unsigned long long)reclaim.calls);
  if(!reclaimOkay){stopWatchdog();return false;}
  State state;Worker workers[8]{};pthread_t threads[8]{};unsigned count=0;
  const uint64_t before=native_allocator_entry_count();
  for(;count<8;++count){workers[count]={&state,count};if(pthread_create(&threads[count],nullptr,work,&workers[count])!=0)break;}
  if(count!=8){
    // Supply sentinel for missing ring producers, so existing workers join.
    for(unsigned i=count;i<8;++i)state.slots[i]=reinterpret_cast<void*>(1);
  }
  state.start=true;bool okay=count==8;
  for(unsigned i=0;i<count;++i){const int joined=pthread_join(threads[i],nullptr);
    if(joined!=0){log("Native allocator worker[%u] join=%d; aborting before uncertain stack teardown",i,joined);abort();}
    okay=(state.ids[i]>0)&&okay;
    for(unsigned j=0;j<i;++j)okay=(state.ids[i]!=state.ids[j])&&okay;
    okay=(state.completed[i]==512)&&okay;
    log("Native allocator worker[%u]: native-id=%d completed=%u/512 error-mask=0x%x",i,state.ids[i],state.completed[i],state.errors[i]);}
  for(auto& slot:state.slots){void* leftover=slot.exchange(nullptr);if(leftover&&leftover!=reinterpret_cast<void*>(1))free(leftover);}
  const uint64_t calls=native_allocator_entry_count()-before;okay=okay&&!state.failed.load()&&calls>=8*512*5;
  int sdkCounter=-1;memcpy(&sdkCounter,__libc+12,sizeof(sdkCounter));
  const auto memory=sdk_direct_heap_stats();
  log("SDK direct heap: live-mappings=%llu live-bytes=%llu allocation-failures=%u map-failures=%u",(unsigned long long)memory.mappings,(unsigned long long)memory.bytes,memory.allocationFailures,memory.mapFailures);
  log("SDK mapped-shrink realloc copy bounds: applied=%llu; medium50201-byte shrink included",(unsigned long long)native_allocator_realloc_copy_fix_count());
  log("Native allocator ownership / 8-thread pattern-realloc-calloc-alignment-handoff: %s protected-entries=%llu SDK-libc+12-lock-gate=%d; private flags unchanged; bin/mmap boundary229360/229361/229376 shrink-grow-zero canaries included",okay?"PASS":"FAIL",(unsigned long long)calls,sdkCounter);
  if(okay)configure_native_allocator_bin_audit(false); // Keep realloc/copy/discard checks; avoid per-malloc/free full scans while browsing.
  stopWatchdog();return okay;
}
}
