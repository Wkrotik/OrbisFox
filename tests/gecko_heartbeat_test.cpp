#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <time.h>
namespace mozilla::widget {
struct OrbisEventDiagnostics { uint32_t stage; uint64_t schedules; uint64_t callbacks; };
static OrbisEventDiagnostics GetOrbisEventDiagnostics() { return {2, 20, 19}; }
}
static uint64_t sceKernelGetProcessTime() { return 123456789; }
namespace orbisfox {
static int firmware_clock_gettime(int, timespec* output) { *output = {123, 456}; return 0; }
}
struct NativeState {
    std::atomic<bool> monitorStop{false};
    std::atomic<uint64_t> progress{0},pollCount{0},monitorFrames{0};
    std::atomic<uint32_t> monitorStage{0};
};
static bool failOpen=false;
static unsigned sleepCalls=0, stopAfter=0;
static NativeState* current=nullptr;
static FILE* testOpen(const char* path,const char* mode) {
    assert(std::strcmp(path,"/data/orbisfox/gecko-heartbeat.log")==0);
    assert(std::strcmp(mode,"w")==0);
    return failOpen?nullptr:std::fopen("build/gecko-heartbeat-host/sample.log",mode);
}
static int sceKernelUsleep(unsigned usec) {
    assert(usec==1000000);++sleepCalls;
    if(stopAfter && sleepCalls>=stopAfter) current->monitorStop.store(true);
    return 0;
}
#define fopen testOpen
#include "monitor-function.inc"
#undef fopen
static std::string output(){
    std::ifstream file("build/gecko-heartbeat-host/sample.log");
    return std::string(std::istreambuf_iterator<char>(file),{});
}
int main(){
    for(int cycle=0;cycle<32;++cycle){
        NativeState state;current=&state;state.progress=123;state.pollCount=45;state.monitorFrames=6;state.monitorStage=8;
        failOpen=false;stopAfter=0;sleepCalls=0;
        assert(monitor(&state)==nullptr);assert(sleepCalls==120);
        auto text=output();assert(text.find("sample=119 progress=123 polls=45 frames=6 stage=8")!=std::string::npos);
        assert(text.find("sample=120 ")==std::string::npos);
        assert(text.find("event=2 scheduled=20 callbacks=19 native_us=123456789")!=std::string::npos);
        assert(text.find("sdk_mono_id=")!=std::string::npos);
        state.monitorStop=true;sleepCalls=0;monitor(&state);
        assert(sleepCalls==0);assert(output().find("sample=")==std::string::npos);
        state.monitorStop=false;stopAfter=3;sleepCalls=0;monitor(&state);
        assert(sleepCalls==3);text=output();assert(text.find("sample=2 ")!=std::string::npos);assert(text.find("sample=3 ")==std::string::npos);
        failOpen=true;sleepCalls=0;monitor(&state);assert(sleepCalls==0);
    }
    puts("Actual native heartbeat monitor: bounded samples / early stop / stop after samples / file failure / atomic field snapshots, 32 cycles PASS (host file/sleep doubles)");
}
