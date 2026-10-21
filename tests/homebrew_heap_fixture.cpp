// SPDX-License-Identifier: MIT
// Host execution is not native allocator or firmware evidence.
#include "orbisfox/native_allocator.h"
#include <atomic>
#include <cstdlib>
#include <pthread.h>
#ifdef ORBISFOX_HEAP_PROBE_HOST
#include <cstdarg>
#include <cstdio>
#include <ctime>
#include <unistd.h>
#include <sys/syscall.h>
namespace {
std::atomic<unsigned> attempts{0};
unsigned failAt;
bool corruptZero;
}
extern "C" void* __real_calloc(size_t,size_t);
extern "C" void* __wrap_calloc(size_t count,size_t size){
    void* value=__real_calloc(count,size);
    if(value && count && size && corruptZero)static_cast<unsigned char*>(value)[0]=0x5a;
    return value;
}
extern "C" int __real_pthread_create(pthread_t*,const pthread_attr_t*,void*(*)(void*),void*);
extern "C" int __wrap_pthread_create(pthread_t* thread,const pthread_attr_t* attr,void*(*fn)(void*),void* arg){
    if(++attempts==failAt)return 11;
    return __real_pthread_create(thread,attr,fn,arg);
}
extern "C" int scePthreadGetthreadid(){return static_cast<int>(syscall(SYS_gettid));}
extern "C" int sceKernelUsleep(unsigned us){return usleep(us);}
extern "C" unsigned long sceKernelGetProcessTime(){
    timespec now{};if(clock_gettime(CLOCK_MONOTONIC,&now))std::abort();
    return static_cast<unsigned long>(now.tv_sec)*1000000+now.tv_nsec/1000;
}
#endif
namespace orbisfox {
void log(const char* format,...){
#ifdef ORBISFOX_HEAP_PROBE_HOST
    va_list args;va_start(args,format);vfprintf(stdout,format,args);va_end(args);fputc('\n',stdout);
#endif
}
}
int main(int argc,char** argv){
#ifdef ORBISFOX_HEAP_PROBE_HOST
    failAt=argc>1?static_cast<unsigned>(std::strtoul(argv[1],nullptr,10)):0;
    corruptZero=argc>2;
    const bool result=orbisfox::probe_native_allocator();
    // Failure injection must propagate failure, without stranding a ring
    // participant or tearing down a live worker's stack-owned state.
    return result==(failAt==0 && !corruptZero)?0:1;
#else
    return !orbisfox::probe_native_allocator();
#endif
}
