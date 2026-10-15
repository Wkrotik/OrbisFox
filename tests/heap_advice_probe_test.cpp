#include "orbisfox/heap_advice_probe.h"
#include <cassert>
#include <cstring>
#include <cstdint>
namespace {
struct Fake {
  alignas(16384) unsigned char storage[8*1024*1024+16384]{};
  bool mapFail=false,misalign=false,adviceFail=false,unmapFail=false,corruptOutside=false,hintOnly=false,live=false;
  unsigned maps=0,advises=0,unmaps=0;size_t bytes=0;void* current=nullptr;
  void reset(){mapFail=misalign=adviceFail=unmapFail=corruptOutside=hintOnly=live=false;maps=advises=unmaps=0;bytes=0;current=nullptr;}
  void* map(size_t n){++maps;if(mapFail)return reinterpret_cast<void*>(UINTPTR_MAX);assert(!live);bytes=n;current=storage+(misalign?1:0);live=true;return current;}
  int advice(void* p,size_t n){++advises;if(adviceFail)return -1;
    if(corruptOutside)std::memset(current,0,bytes);else if(!hintOnly)std::memset(p,0,n);return 0;}
  int unmap(void* p,size_t n){++unmaps;assert(live && p==current && n==bytes);if(unmapFail)return -1;live=false;return 0;}
  orbisfox::HeapAdviceResult run(size_t page=16384){return orbisfox::probe_heap_advice(page,[&](size_t n){return map(n);},[&](void* p,size_t n){return advice(p,n);},[&](void* p,size_t n){return unmap(p,n);});}
} fake;
}
int main(){
  auto r=fake.run();assert(r.safe() && fake.maps==3 && fake.advises==6 && fake.unmaps==3 && !fake.live);
  fake.reset();fake.hintOnly=true;r=fake.run();assert(r.safe() && !fake.live); // BSD advice need not immediately zero the advised pages.
  fake.reset();r=fake.run(4096);assert(r.errorMask==1 && fake.maps==0);
  fake.reset();fake.mapFail=true;r=fake.run();assert(r.errorMask==2 && fake.unmaps==0 && !fake.live);
  fake.reset();fake.misalign=true;r=fake.run();assert(r.errorMask==1 && fake.advises==0 && fake.unmaps==1 && !fake.live);
  fake.reset();fake.adviceFail=true;r=fake.run();assert(r.errorMask==4 && r.adviceResult==-1 && fake.unmaps==1 && !fake.live);
  fake.reset();fake.corruptOutside=true;r=fake.run();assert(r.errorMask==8 && r.failedSpan==256*1024 && r.failedOffset==0 && r.actual==0 && r.expected==0x5d && fake.unmaps==1 && !fake.live);
  fake.reset();fake.unmapFail=true;r=fake.run();assert(r.errorMask==16 && fake.live); // Caller must not abandon uncertain VM ownership.
}
