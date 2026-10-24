// SPDX-License-Identifier: MIT
// Host doubles for the genuine SDK-compiled stack-query object.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <sys/random.h>
extern "C" {uintptr_t __stack_chk_guard;}
namespace js {void* GetNativeStackBaseImpl();}
namespace {int mode, initialized, queried, described, destroyed;uintptr_t storage;}
extern "C" int fixture_attr_init(void** output){
    ++initialized;fputs("INIT\n",stderr);
    if(mode==1)return 35;
    *output=&storage;return 0;
}
extern "C" void* fixture_self(){return reinterpret_cast<void*>(0x1234);}
extern "C" int fixture_attr_get_np(void* thread,void** attribute){
    assert(initialized==1 && *attribute==&storage && thread==reinterpret_cast<void*>(0x1234));
    ++queried;return mode==2?35:0;
}
extern "C" int fixture_attr_getstack(void* const* attribute,void** base,size_t* size){
    assert(*attribute==&storage && queried==1);++described;
    *base=reinterpret_cast<void*>(mode==5?0:mode==7?UINTPTR_MAX-7:0x10000);
    *size=mode==6?0:0x4000;
    return mode==3?35:0;
}
extern "C" int fixture_attr_destroy(void** attribute){
    assert(initialized==1 && *attribute==&storage);++destroyed;
    fprintf(stderr,"DESTROY query=%d stack=%d\n",queried,described);
    *attribute=nullptr;return mode==4?35:0;
}
int main(int argc,char** argv){
    assert(getrandom(&__stack_chk_guard,sizeof(__stack_chk_guard),0)==sizeof(__stack_chk_guard));
    mode=argc>1?std::atoi(argv[1]):0;
    void* stack=js::GetNativeStackBaseImpl();
    assert(mode==0 && stack==reinterpret_cast<void*>(0x14000));
    assert(initialized==1 && queried==1 && described==1 && destroyed==1);
}
