#include "orbisfox/native_stdio.h"
#include "orbisfox/run_logs.h"
#include "orbisfox/presenter.h"
#include <atomic>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <orbis/libkernel.h>
namespace orbisfox {
namespace {
struct Probe {
  FILE* file=nullptr;
  std::atomic<bool> start{false};
  std::atomic<bool> failed{false};
  int nativeIDs[4]{};unsigned legacyIDs[4]{};
};
struct Worker {Probe* state;unsigned index;};
void* writer(void* opaque) {
  auto& worker=*static_cast<Worker*>(opaque);auto& state=*worker.state;
  state.nativeIDs[worker.index]=scePthreadGetthreadid();
  // Observe only the exact location dereferenced by this SDK's __lockfile.
  // It is diagnostic, never used as native thread identity or for locking.
  uintptr_t sdkTCB=0;
  __asm__ volatile("movq %%fs:0, %0":"=r"(sdkTCB));
  if(sdkTCB) memcpy(&state.legacyIDs[worker.index],reinterpret_cast<void*>(sdkTCB+0x38),4);
  while(!state.start.load()) sceKernelUsleep(100);
  for(unsigned line=0;line<1024;++line) {
    if(fprintf(state.file,"worker-%u:%04u OrbisFox stdio lock\n",worker.index,line)!=int(sizeof("worker-0:0000 OrbisFox stdio lock\n")-1))
      state.failed.store(true);
  }
  return nullptr;
}
}
bool probe_native_stdio_locks() {
  if(!initialize_native_stdio_locks()) return false;
  Probe state;Worker workers[4]{};pthread_t threads[4]{};
  if(native_diagnostics_enabled())state.file=fopen(NativeRunLogPath("stdio-lock-probe.log").c_str(),"w+");
  else{
    char temporary[]="/data/orbisfox/cache/stdio-probe-XXXXXX";const int fd=mkstemp(temporary);
    if(fd>=0){const int removed=unlink(temporary);if(removed==0)state.file=fdopen(fd,"w+");if(!state.file)close(fd);}
  }
  if(!state.file) {log("Native stdio contention: fopen failed");return false;}
  unsigned count=0;
  for(;count<4;++count) {
    workers[count]={&state,count};
    if(pthread_create(&threads[count],nullptr,writer,&workers[count])!=0) break;
  }
  const uint64_t entryBefore=native_stdio_entry_lock_count();
  state.start.store(true);
  bool okay=count==4;
  for(unsigned i=0;i<count;++i) {
    const int result=pthread_join(threads[i],nullptr);okay=okay && result==0;
    log("Native stdio identity: worker[%u] native=%d sdk-FS0+0x38=%u",i,state.nativeIDs[i],state.legacyIDs[i]);
  }
  const uint64_t entryDelta=native_stdio_entry_lock_count()-entryBefore;
  okay=okay && entryDelta>=4096 && !state.failed.load() && fflush(state.file)==0 && fseek(state.file,0,SEEK_SET)==0;
  bool seen[4][1024]{};unsigned lines=0;char buffer[128]{};
  while(fgets(buffer,sizeof(buffer),state.file)) {
    unsigned worker=0,line=0;int consumed=0;
    if(sscanf(buffer,"worker-%u:%u OrbisFox stdio lock\n%n",&worker,&line,&consumed)!=2 ||
       consumed!=int(strlen(buffer)) || worker>=4 || line>=1024 || seen[worker][line]) {okay=false;break;}
    seen[worker][line]=true;++lines;
  }
  okay=okay && lines==4096 && !ferror(state.file);
  if(fclose(state.file)!=0)okay=false;
  log("Native genuine stdio entry ownership / 4-thread buffered-file contention: %s lines=%u protected-entries=%llu",okay?"PASS":"FAIL",lines,(unsigned long long)entryDelta);
  return okay;
}
}
