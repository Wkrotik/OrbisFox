// Actual pinned libc++abi guard implementation; explicit native thread-ID double.
#define TESTING_CXA_GUARD
#include "cxa_guard_impl.h"
#include <pthread.h>
#include <atomic>
#include <cassert>
#include <sys/syscall.h>
#include <unistd.h>
#include <sys/wait.h>
extern "C" int32_t scePthreadGetthreadid(void) { return static_cast<int32_t>(syscall(SYS_gettid)); }
using Guard = __cxxabiv1::SelectedImplementation;
struct Round {
  alignas(8) uint64_t guard = 0;
  std::atomic<unsigned> entries{0}, ready{0};
  std::atomic<bool> start{false};
  uint32_t ids[4]{};
};
struct Worker { Round* round; unsigned index; };
void* worker(void* opaque) {
  auto& w=*static_cast<Worker*>(opaque);auto& r=*w.round;
  r.ids[w.index]=__cxxabiv1::PlatformThreadID();r.ready.fetch_add(1);
  while(!r.start.load()) usleep(100);
  Guard guard(&r.guard);
  if(guard.cxa_guard_acquire()==__cxxabiv1::INIT_IS_PENDING) {
    r.entries.fetch_add(1);usleep(20000);guard.cxa_guard_release();
  }
  return nullptr;
}
int main() {
  for(unsigned cycle=0;cycle<32;++cycle) {
    Round round;pthread_t threads[4]{};Worker workers[4]{};
    for(unsigned i=0;i<4;++i) {workers[i]={&round,i};assert(!pthread_create(&threads[i],nullptr,worker,&workers[i]));}
    while(round.ready.load()!=4) usleep(100);round.start.store(true);
    for(auto thread:threads) assert(!pthread_join(thread,nullptr));
    assert(round.entries.load()==1);
    for(unsigned i=0;i<4;++i) for(unsigned j=i+1;j<4;++j)assert(round.ids[i]!=round.ids[j]);
    // Real abort/reset must let a failed initializer be retried, not fake done.
    alignas(8) uint64_t reset=0;Guard aborted(&reset);
    assert(aborted.cxa_guard_acquire()==__cxxabiv1::INIT_IS_PENDING);aborted.cxa_guard_abort();
    Guard retried(&reset);assert(retried.cxa_guard_acquire()==__cxxabiv1::INIT_IS_PENDING);retried.cxa_guard_release();
    // Genuine same-thread recursion must remain fatal.
    const pid_t child=fork();assert(child>=0);
    if(child==0){alignas(8) uint64_t recursive=0;Guard owner(&recursive);owner.cxa_guard_acquire();Guard again(&recursive);again.cxa_guard_acquire();_exit(99);}
    int status=0;assert(waitpid(child,&status,0)==child);assert(WIFSIGNALED(status)&&WTERMSIG(status)==SIGABRT);
  }
}
