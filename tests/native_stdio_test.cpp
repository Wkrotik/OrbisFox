// Actual adapter with host pthreads. Explicit SDK FLOCK caller model: glibc's
// hidden stdio locks are not the firmware SDK and do not certify its FILE ABI.
#include "orbisfox/native_stdio.h"
#include <pthread.h>
#include <stdio.h>
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstring>
#include <stdarg.h>
#include <initializer_list>
extern "C" int __lockfile(FILE*);
extern "C" void __unlockfile(FILE*);
struct Round {FILE* file;std::atomic<unsigned> writers{0};bool skipSDKLock=false;};
// Model SDK fprintf's call to vfprintf, including its FILE.lock=-1 skip case.
int sdkFormat(FILE* file,const char* format,...) {
  va_list args;va_start(args,format);const int result=vfprintf(file,format,args);va_end(args);return result;
}
struct Worker {Round* round;unsigned index;};
void* writer(void* p) {
  auto& worker=*static_cast<Worker*>(p);auto& round=*worker.round;
  for(unsigned line=0;line<256;++line) {
    if(!round.skipSDKLock) {
      assert(__lockfile(round.file)==1);
      assert(round.writers.fetch_add(1)==0);
      // Same thread recursion/trylock must work in the same ownership domain.
      flockfile(round.file);assert(ftrylockfile(round.file)==0);
      funlockfile(round.file);funlockfile(round.file);
    }
    assert(sdkFormat(round.file,"worker-%u:%u\n",worker.index,line)>0);
    if(!round.skipSDKLock) {
      assert(round.writers.fetch_sub(1)==1);
      __unlockfile(round.file);
    }
  }
  return nullptr;
}
void* attempt(void* p) {assert(ftrylockfile(static_cast<FILE*>(p))==EBUSY);return nullptr;}
int main() {
  assert(orbisfox::initialize_native_stdio_locks());
  for(unsigned cycle=0;cycle<32;++cycle) for(bool skip:{false,true}) {
    Round round{tmpfile()};round.skipSDKLock=skip;assert(round.file);
    const uint64_t before=orbisfox::native_stdio_entry_lock_count();
    FILE* other=tmpfile();assert(other);
    flockfile(round.file);pthread_t probe{};
    assert(!pthread_create(&probe,nullptr,attempt,other));assert(!pthread_join(probe,nullptr));
    funlockfile(round.file);assert(!fclose(other));
    pthread_t threads[8]{};Worker workers[8]{};
    for(unsigned i=0;i<8;++i){workers[i]={&round,i};assert(!pthread_create(&threads[i],nullptr,writer,&workers[i]));}
    for(auto thread:threads)assert(!pthread_join(thread,nullptr));
    assert(orbisfox::native_stdio_entry_lock_count()-before>=2048);
    assert(round.writers.load()==0);assert(!fflush(round.file));rewind(round.file);
    char line[80]{};bool seen[8][256]{};unsigned count=0;
    while(fgets(line,sizeof(line),round.file)) {
      unsigned worker=0,index=0;int consumed=0;
      assert(sscanf(line,"worker-%u:%u\n%n",&worker,&index,&consumed)==2);
      assert(consumed==int(strlen(line))&&worker<8&&index<256&&!seen[worker][index]);
      seen[worker][index]=true;++count;
    }
    assert(count==2048&&!ferror(round.file));assert(!fclose(round.file));
  }
}
