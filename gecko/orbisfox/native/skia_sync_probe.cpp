/* Actual linked Skia synchronization gate, before Gecko workers start.
 * Comparison uses SDK sem_t only through its published API, never guesses a
 * ksem handle. Absolute timed wait is bounded; legacy failure is diagnostic.
 */
#include "orbisfox/presenter.h"
#include "include/private/base/SkMutex.h"
#include "../SkiaSemaphore.h"
#include <pthread.h>
#include <semaphore.h>
#include <time.h>
#include <atomic>
#include <cstring>
#include <cerrno>
#include <unistd.h>
#include <cstdlib>
#include <orbis/libkernel.h>
namespace orbisfox {
namespace {
struct State {
  SkMutex mutex;
  SkSemaphore start;
  std::atomic<unsigned> ready{0}, inside{0}, violations{0};
  unsigned value=0, completed[8]{};
  int ids[8]{};
};
struct Argument {State* state;unsigned index;};
struct Watchdog {std::atomic<bool> done{false};uint64_t deadline;};
void* watch(void* opaque) {
  auto& guard=*static_cast<Watchdog*>(opaque);
  while(!guard.done.load()) {
    if(sceKernelGetProcessTime()>=guard.deadline) {
      constexpr char message[]="Skia startup synchronization probe: 20s deadline exceeded; terminating, not returning while workers own state\n";
      write(STDERR_FILENO,message,sizeof(message)-1);
      __builtin_trap(); // No Gecko objects exist yet; never detach live users.
    }
    sceKernelUsleep(10000);
  }
  return nullptr;
}
void* worker(void* opaque) {
  auto& arg=*static_cast<Argument*>(opaque);auto& state=*arg.state;
  state.ids[arg.index]=scePthreadGetthreadid();++state.ready;
  state.start.wait();
  for(unsigned n=0;n<256;++n) {
    SkAutoMutexExclusive lock(state.mutex);
    if(state.inside.fetch_add(1)!=0)++state.violations;
    const unsigned before=state.value;
    sceKernelUsleep(10); // Force overlapping arrivals into actual Skia slow path.
    state.value=before+1;
    if(state.inside.fetch_sub(1)!=1)++state.violations;
    ++state.completed[arg.index];
  }
  return nullptr;
}
bool compareSDK() {
  struct alignas(8) Guarded {unsigned char before[64];sem_t semaphore;unsigned char after[64];} sample;
  memset(&sample,0xa5,sizeof(sample));
  log("Skia optional SDK semaphore comparison: entering sem_init");
  errno=0;const int init=sem_init(&sample.semaphore,0,0);const int initErrno=errno;
  bool guards=true;
  for(auto b:sample.before)guards=guards&&b==0xa5;
  for(auto b:sample.after)guards=guards&&b==0xa5;
  int posted=-999, waited=-999, destroyed=-999, postErrno=0, waitErrno=0;
  if(init==0 && guards) {
    log("Skia optional SDK semaphore comparison: entering sem_post");
    errno=0;posted=sem_post(&sample.semaphore);postErrno=errno;
    if(posted==0) {
      timespec deadline{};
      if(clock_gettime(CLOCK_REALTIME,&deadline)==0) {
        deadline.tv_nsec+=100000000;
        if(deadline.tv_nsec>=1000000000){++deadline.tv_sec;deadline.tv_nsec-=1000000000;}
        log("Skia optional SDK semaphore comparison: entering sem_timedwait with 100ms absolute deadline");
        errno=0;waited=sem_timedwait(&sample.semaphore,&deadline);waitErrno=errno;
      }
    }
    log("Skia optional SDK semaphore comparison: entering sem_destroy");
    destroyed=sem_destroy(&sample.semaphore);
  }
  for(auto b:sample.before)guards=guards&&b==0xa5;
  for(auto b:sample.after)guards=guards&&b==0xa5;
  log("Skia SDK semaphore comparison (not adapter gate): init=%d errno=%d post=%d errno=%d timed-wait=%d errno=%d destroy=%d guards=%d; -999 means not attempted",init,initErrno,posted,postErrno,waited,waitErrno,destroyed,guards);
  return guards;
}
}
bool probe_gecko_skia_sync() {
  Watchdog guard{{false},sceKernelGetProcessTime()+20000000};pthread_t monitor{};
  const int monitorResult=pthread_create(&monitor,nullptr,watch,&guard);
  if(monitorResult!=0){log("Skia synchronization watchdog create=%d",monitorResult);return false;}
  // Unknown SDK ksem behavior must not make the legacy comparison a mandatory
  // gate. Explicit marker opts in; no marker is created by the application.
  bool guardsOkay=true;
  if(access("/data/orbisfox/probe-sdk-semaphore",F_OK)==0)guardsOkay=compareSDK();
  else log("Skia SDK semaphore comparison: NOT TESTED (optional /data/orbisfox/probe-sdk-semaphore)");
  const uint64_t creationsBefore=OrbisSkiaSemaphore::creations.load();
  const uint64_t waitsBefore=OrbisSkiaSemaphore::waits.load();
  const uint64_t sleepsBefore=OrbisSkiaSemaphore::sleeps.load();
  State state;Argument arguments[8]{};pthread_t threads[8]{};unsigned count=0;
  for(;count<8;++count) {
    arguments[count]={&state,count};
    int rc=pthread_create(&threads[count],nullptr,worker,&arguments[count]);
    if(rc!=0){log("Skia synchronization probe: create[%u]=%d",count,rc);break;}
  }
  const uint64_t deadline=sceKernelGetProcessTime()+2000000;
  while(state.ready.load()<count && sceKernelGetProcessTime()<deadline)sceKernelUsleep(1000);
  bool okay=guardsOkay && count==8 && state.ready==count;
  while(count && OrbisSkiaSemaphore::sleeps.load()==sleepsBefore && sceKernelGetProcessTime()<deadline)sceKernelUsleep(1000);
  // Join retains stack/object ownership even after a readiness deadline. The
  // wait primitive itself is not forcibly interrupted or falsely declared OK.
  if(count)state.start.signal(count);
  for(unsigned i=0;i<count;++i) {
    int rc=pthread_join(threads[i],nullptr);
    if(rc!=0){log("Skia synchronization join[%u]=%d; termination uncertain, aborting before stack teardown",i,rc);abort();}
    okay=okay&&rc==0&&state.completed[i]==256&&state.ids[i]>0;
    for(unsigned j=0;j<i;++j)okay=okay&&state.ids[i]!=state.ids[j];
    log("Skia synchronization worker[%u]: native-id=%d completed=%u/256 join=%d",i,state.ids[i],state.completed[i],rc);
  }
  okay=okay&&state.violations==0&&state.value==8*256&&state.inside==0;
  const uint64_t creations=OrbisSkiaSemaphore::creations.load()-creationsBefore;
  const uint64_t waits=OrbisSkiaSemaphore::waits.load()-waitsBefore;
  const uint64_t sleeps=OrbisSkiaSemaphore::sleeps.load()-sleepsBefore;
  okay=okay&&creations>0&&waits>0&&sleeps>0;
  log("Skia actual semaphore / mutex contention: %s acquisitions=%u violations=%u os-created=%llu os-waits=%llu cond-waits=%llu; observed exclusion/completion, not website stability proof",okay?"PASS":"FAIL",state.value,state.violations.load(),static_cast<unsigned long long>(creations),static_cast<unsigned long long>(waits),static_cast<unsigned long long>(sleeps));
  guard.done.store(true);
  const int monitorJoin=pthread_join(monitor,nullptr);
  if(monitorJoin!=0){log("Skia synchronization watchdog join=%d; aborting before stack teardown",monitorJoin);abort();}
  return okay;
}
}
