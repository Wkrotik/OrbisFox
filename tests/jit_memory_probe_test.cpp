// Actual allocator/probe algorithm with explicit firmware-API doubles backed
// by real host shared-file RX/RW mappings. Not firmware or SpiderMonkey proof.
#include "orbisfox/jit_memory_probe.h"
#include <sys/mman.h>
#include <unistd.h>
#include <stdlib.h>
#include <cassert>
using namespace orbisfox;
struct Fake {
  int fault=-1,fd=-1,alias=-1;void *rx=nullptr,*rw=nullptr;unsigned descriptors=0,mappings=0;
  JitMemoryBackend backend(){return {this,
    [](void* p,int flags,size_t size,int permissions,int* out)->int32_t {
      auto& f=*static_cast<Fake*>(p);assert(flags==0&&size==16384&&permissions==7);
      if(f.fault==0)return -1;
      char path[]="/tmp/orbisfox-jit-XXXXXX";f.fd=mkstemp(path);assert(f.fd>=0);unlink(path);assert(!ftruncate(f.fd,size));
      *out=f.fd;++f.descriptors;return 0;
    },
    [](void* p,int fd,int permissions,int* out)->int32_t {
      auto& f=*static_cast<Fake*>(p);assert(fd==f.fd&&permissions==3);
      if(f.fault==1)return -1;
      if(f.fault==6){*out=fd;return 0;}
      *out=f.alias=dup(fd);assert(*out>=0);++f.descriptors;return 0;
    },
    [](void* p,int fd,int permissions,void** out)->int32_t {
      auto& f=*static_cast<Fake*>(p);assert(permissions==5||permissions==3);
      if((permissions==5&&f.fault==2)||(permissions==3&&f.fault==3))return -1;
      if(permissions==3&&f.fault==5){*out=f.rx;return 0;}
      *out=mmap(nullptr,16384,permissions,(f.fault==7&&permissions==3)?MAP_PRIVATE:MAP_SHARED,fd,0);
      assert(*out!=MAP_FAILED);++f.mappings;
      if(permissions==5)f.rx=*out;else f.rw=*out;return 0;
    },
    [](void* p,void* address,size_t size,int permissions) {
      auto& f=*static_cast<Fake*>(p);assert(size==16384);
      if(f.fault==4)return false;
      return (address==f.rx&&permissions==5)||(address==f.rw&&permissions==3);
    },
    [](void* p,void* address,size_t size) {
      auto& f=*static_cast<Fake*>(p);assert(f.mappings>0);--f.mappings;assert(!munmap(address,size));return f.fault==8?-1:0;
    },
    [](void* p,int fd){auto& f=*static_cast<Fake*>(p);assert(f.descriptors>0);--f.descriptors;assert(!close(fd));return f.fault==9?-1:0;}};}
};
int main() {
  for(unsigned cycle=0;cycle<32;++cycle) {
    Fake good;auto result=probeJitMemory(good.backend());
    assert(result.okay&&result.sharedBytes&&result.first==42&&result.patched==43&&result.rxNotWritable&&result.rwNotExecutable&&result.cleanup);
    assert(good.descriptors==0&&good.mappings==0);
    for(int fault=0;fault<10;++fault) {
      Fake bad;bad.fault=fault;result=probeJitMemory(bad.backend());assert(!result.okay);
      assert(bad.descriptors==0&&bad.mappings==0);
      if(fault<8)assert(result.first==-1);
      else assert(!result.cleanup);
    }
  }
}
