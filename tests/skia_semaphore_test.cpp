// Actual pinned SkSemaphore/SkMutex and the Orbis OSSemaphore adapter.
// Host pthreads are genuine; error injection is explicit, not firmware proof.
#include "include/private/base/SkMutex.h"
#include "orbisfox/SkiaSemaphore.h"
#include <atomic>
#include <cassert>
#include <thread>
#include <vector>
#include <cstdio>
#include <cstdarg>
#include <cstdlib>
#include <cerrno>
#include <cstring>
#include <csignal>
#include <sys/wait.h>
#include <unistd.h>

void SkDebugf(const char* fmt, ...) {va_list args;va_start(args,fmt);vfprintf(stderr,fmt,args);va_end(args);}
[[noreturn]] void sk_abort_no_print() {abort();}
bool sk_abort_is_enabled() {return true;}
static const char* failure=nullptr;
static std::atomic<unsigned> waitEntries{0};
#define WRAP(name, params, args) \
extern "C" int __real_##name params; \
extern "C" int __wrap_##name params { \
    if(failure && !strcmp(failure,#name))return EINVAL; \
    return __real_##name args; \
}
WRAP(pthread_mutex_init,(pthread_mutex_t* m,const pthread_mutexattr_t* a),(m,a))
WRAP(pthread_mutex_destroy,(pthread_mutex_t* m),(m))
WRAP(pthread_mutex_lock,(pthread_mutex_t* m),(m))
WRAP(pthread_mutex_unlock,(pthread_mutex_t* m),(m))
WRAP(pthread_cond_init,(pthread_cond_t* c,const pthread_condattr_t* a),(c,a))
WRAP(pthread_cond_destroy,(pthread_cond_t* c),(c))
WRAP(pthread_cond_broadcast,(pthread_cond_t* c),(c))
extern "C" int __real_pthread_cond_wait(pthread_cond_t*,pthread_mutex_t*);
extern "C" int __wrap_pthread_cond_wait(pthread_cond_t* c,pthread_mutex_t* m){
    unsigned n=++waitEntries;
    if(failure && !strcmp(failure,"pthread_cond_wait"))return EINVAL;
    if(n%7==0)return 0; // Explicit spurious wake; mutex still owned.
    return __real_pthread_cond_wait(c,m);
}

int main(){
    alarm(45);
    for(unsigned cycle=0;cycle<32;++cycle){
        SkMutex mutex;
        std::atomic<unsigned> inside{0}, ready{0};
        unsigned value=0;
        SkSemaphore gate;
        std::vector<std::thread> threads;
        for(unsigned i=0;i<8;++i)threads.emplace_back([&]{
            ++ready;gate.wait();
            for(unsigned n=0;n<256;++n){
                SkAutoMutexExclusive hold(mutex);
                assert(inside.fetch_add(1)==0);
                unsigned old=value;std::this_thread::yield();value=old+1;
                assert(inside.fetch_sub(1)==1);
            }
        });
        while(ready.load()!=8)std::this_thread::yield();
        gate.signal(8); // Also exercises signal-before-lazy-OS-wait races.
        for(auto& thread:threads)thread.join();
        assert(value==8*256 && inside==0);
        assert(!gate.try_wait());gate.signal(3);
        unsigned acquired=0;while(acquired<3)if(gate.try_wait())++acquired;
        assert(!gate.try_wait());
        OrbisSkiaSemaphore before;before.signal(3);before.wait();before.wait();before.wait();
    }
    assert(waitEntries>0); // Must actually exercise slow-path, not only atomics.
    for(const char* api:{"pthread_mutex_init","pthread_cond_init","pthread_mutex_lock",
                        "pthread_mutex_unlock","pthread_cond_broadcast","pthread_cond_wait",
                        "pthread_cond_destroy","pthread_mutex_destroy"}){
        pid_t pid=fork();assert(pid>=0);
        if(pid==0){
            alarm(2);failure=api;
            {OrbisSkiaSemaphore semaphore;
             if(!strcmp(api,"pthread_cond_wait"))semaphore.wait();
             else{semaphore.signal(1);semaphore.wait();}}
            _exit(99);
        }
        int status=0;assert(waitpid(pid,&status,0)==pid);
        assert(WIFSIGNALED(status)&&WTERMSIG(status)==SIGABRT);
    }
    printf("Pinned Skia semaphore/mutex: 32 cycles x 8 workers x 256 acquisitions; exclusion, permits, lazy contention, spurious wakes and 8 fatal primitive failures PASS; host pthreads, not firmware\n");
}
