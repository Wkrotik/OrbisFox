// SPDX-License-Identifier: MIT
// Process-termination doubles only; not console shutdown/atexit evidence.
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <ctime>
extern "C" [[noreturn]] void catchReturnFromMain(int);
namespace {
int mode, sleeps, clocks;
bool automaticDestroyed;
struct Automatic { ~Automatic() { automaticDestroyed=true; } };
int applicationMain(){Automatic local;return 17;}
}
namespace orbisfox {
void log(const char* format,...){va_list args;va_start(args,format);vfprintf(stderr,format,args);va_end(args);fputc('\n',stderr);}
int request_system_exit(){
    if(!automaticDestroyed)std::_Exit(1);
    if(mode==0)std::_Exit(73); // Genuine manager could terminate immediately.
    return mode==1?-1:0;
}
}
extern "C" int clock_gettime(clockid_t, timespec* output){
    ++clocks;if(mode==3)return -1;
    output->tv_sec=mode==4?1:clocks;
    output->tv_nsec=0;
    if(mode==6 && clocks>1)output->tv_sec=0;
    return 0;
}
extern "C" int sceKernelUsleep(unsigned){
    ++sleeps;
    if(mode==7)std::_Exit(73); // Accepted request can complete asynchronously.
    if(mode==4 && sleeps>500)std::_Exit(2);
    return mode==5?-1:0;
}
int main(int argc,char** argv){
    mode=argc>1?std::atoi(argv[1]):0;
    catchReturnFromMain(applicationMain());
}
