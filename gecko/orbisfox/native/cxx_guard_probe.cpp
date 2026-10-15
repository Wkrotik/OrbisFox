/* Genuine compiler-emitted C++ static guard contention, before WebRender. */
#include "orbisfox/presenter.h"
#include <atomic>
#include <pthread.h>
#include <orbis/libkernel.h>
namespace orbisfox {
namespace {
struct GuardProbe {
  std::atomic<unsigned> ready{0}, entered{0};
  std::atomic<bool> start{false}, valid{false};
  int ids[4]{}; unsigned values[4]{};
};
constinit GuardProbe probe;
unsigned guardedValue() {
  static const unsigned value = [] {
    probe.entered.fetch_add(1);
    sceKernelUsleep(50000); // Deliberate overlap; other threads must wait.
    return 0x47554152u;
  }();
  return value;
}
void* worker(void* opaque) {
  const unsigned index = static_cast<unsigned>(reinterpret_cast<uintptr_t>(opaque));
  probe.ids[index] = scePthreadGetthreadid();
  probe.ready.fetch_add(1);
  while (!probe.start.load()) sceKernelUsleep(1000);
  if (probe.valid.load()) probe.values[index] = guardedValue();
  return nullptr;
}
}
bool probe_gecko_cxx_guards() {
  // Single startup invocation: retain genuine factory-once semantics.
  pthread_t threads[4]{}; unsigned count=0;
  for (; count<4; ++count) {
    const int result=pthread_create(&threads[count],nullptr,worker,reinterpret_cast<void*>(uintptr_t(count)));
    if (result) {log("C++ guard probe: pthread_create[%u]=%d",count,result);break;}
  }
  const uint64_t deadline=sceKernelGetProcessTime()+1000000;
  while (probe.ready.load()<count && sceKernelGetProcessTime()<deadline) sceKernelUsleep(1000);
  bool okay=count==4 && probe.ready.load()==4;
  const int mainID=scePthreadGetthreadid();
  okay=okay && mainID>0;
  if (probe.ready.load()==count) {
    for(unsigned i=0;i<count;++i) {
      okay=okay && probe.ids[i]>0 && probe.ids[i]!=mainID;
      for(unsigned j=0;j<i;++j) okay=okay && probe.ids[i]!=probe.ids[j];
    }
  }
  // Never exercise recursive owner logic if native identity itself is invalid.
  // Still release/join all created workers; the callback honors this gate.
  probe.valid.store(okay);
  probe.start.store(true);
  for(unsigned i=0;i<count;++i) {
    const int joined=pthread_join(threads[i],nullptr);
    okay=okay && joined==0 && probe.values[i]==0x47554152u;
    log("C++ guard probe: worker[%u] native-id=%d value=0x%x join=%d",i,probe.ids[i],probe.values[i],joined);
  }
  okay=okay && probe.entered.load()==1;
  log("C++ real static guard contention / native identities: %s main-id=%d initializer-count=%u",
      okay?"PASS":"FAIL",mainID,probe.entered.load());
  return okay;
}
}
