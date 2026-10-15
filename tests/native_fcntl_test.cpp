// Actual SQLite-only adapter, explicit resident module/firmware/SDK doubles.
// Not firmware contention, persistent SQLite, networking or security proof.
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstring>
#include <cstdarg>
#include <fcntl.h>
#include <unistd.h>
#include <thread>
#include <vector>
#include <orbis/libkernel.h>
#include "orbisfox/native_fcntl.h"
static std::atomic<int> lists{0}, calls{0}, lastCommand{-1};
static std::atomic<uintptr_t> lastArgument{0};
static int failure=0,corrupt=0,outputType=2,outputSysid=0;
static orbisfox::FirmwareFlock lastLock{};
static bool unavailable=false,nonExecutable=false;
static int fakeFcntl(int, int command, ...) {
    ++calls; lastCommand=command;
    if(failure) {errno=failure;return -1;}
    if(command==F_GETFD || command==F_GETFL || command==F_GETOWN) return 0;
    va_list args;va_start(args,command);lastArgument=va_arg(args,uintptr_t);va_end(args);
    if(command==F_GETLK || command==F_SETLK || command==F_SETLKW) {
        auto* value=reinterpret_cast<orbisfox::FirmwareFlock*>(lastArgument.load());
        if(value->type!=1 && value->type!=2 && value->type!=3) {errno=EINVAL;return -1;}
        lastLock=*value;
        if(command==F_GETLK) {value->type=outputType;value->pid=123;value->sysid=outputSysid;}
        if(corrupt) reinterpret_cast<unsigned char*>(value)[sizeof(*value)]=0;
        return 0;
    }
    return static_cast<int>(lastArgument.load());
}
int sceKernelGetModuleList(OrbisKernelModule* output,size_t,size_t* count) {
    ++lists;if(unavailable)return -1;output[0]=5;*count=1;return 0;
}
int sceKernelGetModuleInfo(OrbisKernelModule,OrbisKernelModuleInfo* info) {strcpy(info->name,"libkernel.sprx");return 0;}
int sceKernelDlsym(OrbisKernelModule,const char* name,void** output) {
    assert(!strcmp(name,"_fcntl"));*output=reinterpret_cast<void*>(fakeFcntl);return 0;
}
int sceKernelQueryMemoryProtection(const void*,void** low,void** high,int32_t* protection) {
    *low=reinterpret_cast<void*>(1);*high=reinterpret_cast<void*>(UINTPTR_MAX);
    *protection=nonExecutable?0:ORBIS_KERNEL_PROT_CPU_EXEC;return 0;
}
namespace orbisfox {void log(const char*,...) {}}
static int testOpen(const char*,int,...) {return 7;}
static int testClose(int fd) {assert(fd==7);return 0;}
static int testFrontend(int fd,int command,...) {
    if(command==F_GETFD || command==F_GETFL || command==F_GETOWN) return fakeFcntl(fd,command);
    va_list args;va_start(args,command);const int argument=va_arg(args,int);va_end(args);
    return fakeFcntl(fd,command,static_cast<uintptr_t>(argument));
}
#define ORBISFOX_FULL_GECKO 1
#define open testOpen
#define close testClose
#define fcntl testFrontend
#include "actual-native-fcntl.inc"
#undef open
#undef close
#undef fcntl
static void reset() {
    binding.store(0);nativeFcntl=nullptr;lists=calls=0;
    failure=corrupt=outputSysid=0;outputType=2;unavailable=nonExecutable=false;
}
int main() {
    for(int cycle=0;cycle<32;++cycle) {
        reset();struct flock value{};value.l_start=1234567890123;value.l_len=9876543210;
        value.l_pid=9;value.l_whence=SEEK_CUR;
        for(int command:{F_SETLK,F_SETLKW,F_GETLK}) for(int type:{F_RDLCK,F_WRLCK,F_UNLCK}) {
            value.l_type=type;
            assert(orbisfox_sqlite_fcntl(7,command,&value)==0);
            assert(lastLock.type==(type==F_RDLCK?1:type==F_WRLCK?3:2));
            assert(lastLock.start==value.l_start && lastLock.length==value.l_len && lastLock.whence==SEEK_CUR);
            if(command==F_GETLK)assert(value.l_type==F_UNLCK && value.l_pid==123);
        }
        assert(lists==1);
        assert(orbisfox_sqlite_fcntl(7,F_SETLK,static_cast<struct flock*>(nullptr))==-1 && errno==EFAULT);
        value.l_type=99;int before=calls;
        assert(orbisfox_sqlite_fcntl(7,F_SETLK,&value)==-1 && errno==EINVAL && calls==before);
        value.l_type=F_RDLCK;
        failure=EAGAIN;assert(orbisfox_sqlite_fcntl(7,F_SETLK,&value)==-1 && errno==EAGAIN);
        failure=EBADF;assert(orbisfox_sqlite_fcntl(-1,F_GETFD)==-1 && errno==EBADF);failure=0;
        for(int type:{1,2,3}) {
            outputType=type;value.l_type=F_RDLCK;
            assert(orbisfox_sqlite_fcntl(7,F_GETLK,&value)==0);
            assert(value.l_type==(type==1?F_RDLCK:type==3?F_WRLCK:F_UNLCK));
        }
        for(int mode=0;mode<3;++mode) {
            value.l_type=F_RDLCK;struct flock original=value;
            outputType=mode==0?5:2;outputSysid=mode==1?1:0;corrupt=mode==2;
            assert(orbisfox_sqlite_fcntl(7,F_GETLK,&value)==-1);
            assert(errno==(mode==2?EOVERFLOW:EPROTO));assert(!memcmp(&value,&original,sizeof(value)));
        }
        corrupt=outputSysid=0;outputType=2;
        assert(orbisfox_sqlite_fcntl(7,F_SETFL,42)==42 && lastArgument==42);
        assert(orbisfox_sqlite_fcntl(7,1030,19)==19 && lastCommand==1030);
        assert(orbisfox_sqlite_fcntl(7,F_GETFL)==0);
        assert(orbisfox::probe_native_file_locks());
        reset();unavailable=true;value.l_type=F_RDLCK;
        assert(orbisfox_sqlite_fcntl(7,F_SETLK,&value)==-1 && errno==ENOSYS);unavailable=false;
        assert(orbisfox_sqlite_fcntl(7,F_SETLK,&value)==-1 && errno==ENOSYS && lists==1);
        reset();nonExecutable=true;assert(orbisfox_sqlite_fcntl(7,F_SETLK,&value)==-1 && errno==ENOSYS);
        reset();std::vector<std::thread> threads;
        for(int i=0;i<8;++i)threads.emplace_back([] {assert(bind());});
        for(auto& thread:threads)thread.join();assert(lists==1);
    }
}
