// Demonstrate the old pinned POSIX path falsely granting mutex entry after
// an explicitly injected EINVAL. No firmware failure is inferred from this.
#include "include/private/base/SkMutex.h"
#include <atomic>
#include <thread>
#include <cassert>
#include <cstdio>
#include <cstdarg>
#include <cstdlib>
#include <cerrno>
#include <semaphore.h>
#include <unistd.h>
void SkDebugf(const char* fmt,...){va_list a;va_start(a,fmt);vfprintf(stderr,fmt,a);va_end(a);}
[[noreturn]] void sk_abort_no_print(){abort();}
bool sk_abort_is_enabled(){return true;}
extern "C" int __wrap_sem_init(sem_t*,int,unsigned){return 0;}
extern "C" int __wrap_sem_destroy(sem_t*){return 0;}
extern "C" int __wrap_sem_post(sem_t*){return 0;}
extern "C" int __wrap_sem_wait(sem_t*){errno=EINVAL;return -1;}
int main(){
  alarm(5);SkMutex lock;std::atomic<unsigned> inside{0};
  lock.acquire();++inside;
  std::thread other([&]{lock.acquire();++inside;lock.release();});
  other.join();unsigned observed=inside.load();lock.release();
  // Do not compile this assertion away: -DNDEBUG disables Skia owner writes
  // for this deliberately broken mutual-exclusion demonstration.
  if(observed!=2)return 1;
  puts("Original pinned Skia POSIX path: injected sem_wait EINVAL falsely allowed second mutex entrant; reproduced host failure mechanism, NOT firmware diagnosis");
}
