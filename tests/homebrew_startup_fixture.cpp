// SPDX-License-Identifier: MIT
// Host-only service doubles; native builds of this fixture are link checks only.
#include <orbis/libkernel.h>
#include "orbisfox/run_logs.h"
#include <assert.h>
#include <fcntl.h>
#include <string.h>

#ifndef DIAGNOSTICS
#define DIAGNOSTICS 0
#endif
namespace {
unsigned initialized, constructed, opened, closed, writes;
bool mainRan;
char captured[1024];size_t used;
}
namespace orbisfox {
bool initialize_native_run_logs() { assert(!constructed);++initialized;return true; }
bool native_diagnostics_enabled() { return DIAGNOSTICS != 0; }
bool copy_native_run_log_path(char* output,size_t capacity,const char* name) {
    assert(!constructed && strcmp(name,"startup-layout.log")==0);
    constexpr char path[]="/mock/startup-layout.log";
    assert(capacity>=sizeof(path));memcpy(output,path,sizeof(path));return true;
}
}
extern "C" {
int32_t sceKernelMkdir(const char* path,OrbisKernelMode mode) {
    assert(!constructed && strcmp(path,"/data/orbisfox")==0 && mode==0700);return 0;
}
int32_t sceKernelOpen(const char* path,int32_t flags,OrbisKernelMode mode) {
    assert(!constructed && initialized==1 && DIAGNOSTICS);
    assert(strcmp(path,"/mock/startup-layout.log")==0 && mode==0600);
    assert(flags==(O_WRONLY|O_CREAT|O_EXCL));++opened;return 47;
}
int32_t sceKernelClose(int32_t fd) { assert(fd==47 && !constructed);++closed;return 0; }
size_t sceKernelWrite(int32_t fd,const void* bytes,size_t count) {
    assert(fd==47 && DIAGNOSTICS && !constructed && used+count<sizeof(captured));
    memcpy(captured+used,bytes,count);used+=count;captured[used]=0;++writes;return count;
}
}
namespace {
struct Owner {
    Owner() { assert(initialized==1 && !constructed);++constructed; }
    ~Owner() { assert(constructed==1 && mainRan); }
} owner;
}
int main() {
    assert(initialized==1 && constructed==1);
    if(DIAGNOSTICS) {
        assert(opened==1 && closed==1 && writes>0);
        assert(strstr(captured,"CRT owns constructors") && strstr(captured,"PREINIT COMPLETED"));
        assert(!strstr(captured,"ALL STATIC INITIALIZERS COMPLETED"));
    } else {
        assert(!opened && !closed && !writes);
    }
    mainRan=true;return 0;
}
