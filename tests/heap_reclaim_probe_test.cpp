#include "orbisfox/heap_reclaim_probe.h"
#include <cassert>
#include <cstdio>
#include <cstring>

namespace {
// Explicit allocator double: exercises probe logic/cleanup, NOT SDK bins or VM.
struct Fake {
  struct Record {unsigned char* p=nullptr;size_t size=0;};
  alignas(32) unsigned char arena[3*1024*1024]{};
  Record records[64]{};
  size_t offset=0;unsigned attempts=0,failAt=0,live=0,resizeCount=0,damageResizeAt=0;
  bool dirtyZero=false,damageNeighbor=false,damageResize=false,separateChunks=false;unsigned char* left=nullptr;
  void reset(){offset=0;attempts=0;failAt=0;live=0;resizeCount=0;damageResizeAt=0;dirtyZero=false;damageNeighbor=false;damageResize=false;separateChunks=false;left=nullptr;for(auto& r:records)r={};}
  void progress(unsigned){assert(live==0);offset=0;left=nullptr;}
  void* allocate(size_t n){
    if(++attempts==failAt)return nullptr;
    const size_t chunk=(n+16+31)&~size_t(31);assert(offset+chunk<=sizeof(arena));
    auto* p=arena+offset+16;offset+=chunk+(separateChunks?32:0);
    for(auto& r:records)if(!r.p){r={p,n};++live;if(!left && n==8192)left=p;return p;}
    assert(false);return nullptr;
  }
  void release(void* p){
    for(auto& r:records)if(r.p==p){
      if(damageNeighbor && r.size==65536){left[0]^=1;damageNeighbor=false;}
      r={};--live;return;
    }
    assert(false);
  }
  void* resize(void* p,size_t n){
    for(const auto& r:records)if(r.p==p){
      const size_t old=r.size;++resizeCount;void* fresh=allocate(n);
      if(fresh){std::memcpy(fresh,p,old<n?old:n);if(damageResize && (!damageResizeAt || resizeCount==damageResizeAt))static_cast<unsigned char*>(fresh)[0]^=1;release(p);}return fresh;
    }
    assert(false);return nullptr;
  }
  void* zero(size_t count,size_t size){void* p=allocate(count*size);if(p)std::memset(p,dirtyZero?1:0,count*size);return p;}
  unsigned boundary(unsigned sample){
    return orbisfox::probe_heap_boundary([&](size_t n){return allocate(n);},
      [&](size_t n,size_t s){return zero(n,s);},[&](void* p,size_t n){return resize(p,n);},
      [&](void* p){release(p);},sample,0x5c);
  }
  orbisfox::HeapReclaimResult run(){
    return orbisfox::probe_heap_reclaim([&](size_t n){return allocate(n);},
      [&](size_t n,size_t s){return zero(n,s);},[&](void* p,size_t n){return resize(p,n);},
      [&](void* p){release(p);},[&](unsigned r){progress(r);});
  }
};
}
int main(){
  static_assert(((orbisfox::heap_boundary_request(0)+47)&~size_t(31))==229376);
  static_assert(((orbisfox::heap_boundary_request(1)+47)&~size_t(31))>229376);
  static_assert(((orbisfox::heap_boundary_request(2)+47)&~size_t(31))>229376);
  static Fake fake;
  for(unsigned sample=0;sample<3;++sample){
    fake.reset();assert(fake.boundary(sample)==0 && fake.live==0 && fake.attempts==5);
    for(unsigned failure=1;failure<=5;++failure){
      fake.reset();fake.failAt=failure;assert(fake.boundary(sample)!=0 && fake.live==0);
    }
    fake.reset();fake.dirtyZero=true;assert(fake.boundary(sample)&64);assert(fake.live==0);
    fake.reset();fake.damageResize=true;fake.damageResizeAt=1;assert(fake.boundary(sample)&4);assert(fake.live==0);
    fake.reset();fake.damageResize=true;fake.damageResizeAt=2;assert(fake.boundary(sample)&256);assert(fake.live==0);
    fake.reset();fake.damageResize=true;fake.damageResizeAt=3;assert(fake.boundary(sample)&16);assert(fake.live==0);
  }
  fake.reset();fake.separateChunks=true;
  const auto uncovered=fake.run();
  assert(!uncovered.okay() && uncovered.completed==32 && uncovered.adjacentGroups==0 && uncovered.errorMask==0 && fake.live==0);
  for(unsigned cycle=0;cycle<32;++cycle){
    fake.reset();auto result=fake.run();assert(result.okay() && result.adjacentGroups==32 && fake.live==0 && result.calls==2112);
    // Every allocation in first round, including either realloc failure, must
    // release remaining original ownership and return explicit failure.
    for(unsigned failure=1;failure<=34;++failure){fake.reset();fake.failAt=failure;result=fake.run();assert(!result.okay() && result.errorMask && result.completed==0 && fake.live==0);}
    fake.reset();fake.damageNeighbor=true;result=fake.run();assert(result.errorMask&2);assert(fake.live==0);
    fake.reset();fake.dirtyZero=true;result=fake.run();assert(result.errorMask&1024);assert(fake.live==0);
  }
  std::puts("Heap reclaim probe:32 cycles allocation/reallocation-failure cleanup, zero contents and neighboring live canaries; boundary229360/229361/229376 cleanup and corruption tests; explicit allocator double, not SDK/firmware proof");
}
