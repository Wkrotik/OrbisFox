#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>

namespace orbisfox {
// Audited musl64 rounds request +16-byte overhead to32-byte alignment.
// 229360 rounds to the final bin-sized chunk (229376); the other requests
// round above MMAP_THRESHOLD. Starting at229376 would test mmap only.
constexpr size_t heap_boundary_request(unsigned sample) {
  constexpr size_t sizes[]={229360,229361,229376};
  return sizes[sample%3];
}
// Same boundary canaries in the native eight-worker gate and host matrices.
// Realloc failure retains original ownership; every path releases it.
template<class Allocate,class Zero,class Resize,class Release>
unsigned probe_heap_boundary(Allocate allocate,Zero zero,Resize resize,
                             Release release,unsigned sample,unsigned char value) {
  const size_t size=heap_boundary_request(sample);
  const auto matches=[](const unsigned char* p,size_t n,unsigned char expected){
    for(size_t i=0;i<n;++i)if(p[i]!=expected)return false;
    return true;
  };
  unsigned error=0;
  auto* p=static_cast<unsigned char*>(allocate(size));
  if(!p)error|=1;
  else {
    memset(p,value,size);
    auto* grown=static_cast<unsigned char*>(resize(p,size+262144));
    if(!grown)error|=2;
    else {
      p=grown;if(!matches(p,size,value))error|=4;
      memset(p+size,value,262144);
      // Above a native page but below the mmap threshold: unlike127, this
      // exercises SDK's buggy mapped-shrink fallback when mremap is ENOSYS.
      auto* medium=static_cast<unsigned char*>(resize(p,50201));
      if(!medium)error|=128;
      else {
        p=medium;if(!matches(p,50201,value))error|=256;
        auto* shrunk=static_cast<unsigned char*>(resize(p,127));
        if(!shrunk)error|=8;
        else {p=shrunk;if(!matches(p,127,value))error|=16;}
      }
    }
    release(p);
  }
  p=static_cast<unsigned char*>(zero(1,size));
  if(!p)error|=32;
  else {if(!matches(p,size,0))error|=64;release(p);}
  return error;
}
struct HeapReclaimResult {
  unsigned completed=0, adjacentGroups=0, errorMask=0;
  uint64_t calls=0;
  bool okay() const {return completed==32 && adjacentGroups>0 && errorMask==0;}
};
// Exercise sub-mmap-threshold chunks, coalescing beyond the audited SDK's
// 163840-byte reclaim and 229376-byte top-bin thresholds, then small splits.
// Actual adjacency is observed, not assumed from allocator API semantics.
// This is a bounded canary probe, not a diagnosis or replacement allocator.
// Run before concurrent engine startup and before guarded allocation mode.
template<class Allocate,class Zero,class Resize,class Release,class Progress>
HeapReclaimResult probe_heap_reclaim(Allocate allocate,Zero zero,Resize resize,
                                    Release release,Progress progress) {
  HeapReclaimResult result;
  const auto alloc=[&](size_t n){++result.calls;return static_cast<unsigned char*>(allocate(n));};
  const auto drop=[&](void* p){if(p){++result.calls;release(p);}};
  const auto matches=[](const unsigned char* p,size_t n,unsigned char value){
    for(size_t i=0;i<n;++i)if(p[i]!=value)return false;
    return true;
  };
  for(unsigned round=0;round<32;++round) {
    progress(round);
    unsigned error=0;
    // Keep enough simultaneous chunks to reach the SDK's geometric arena
    // growth. Four repeated chunks alone can reuse separate small arenas
    // forever and never exercise a contiguous large free run.
    auto* left=alloc(8192);unsigned char* blocks[24]{};
    for(auto& p:blocks)p=alloc(65536);
    auto* right=alloc(8192);
    if(!left || !right)error|=1;
    for(auto* p:blocks)if(!p)error|=1;
    if(!error) {
      memset(left,0x41,8192);memset(right,0x72,8192);
      unsigned adjacent=1,best=1;
      for(unsigned i=0;i<24;++i) {
        memset(blocks[i],int(0x90+i),65536);
        if(i) {
          // Native/public audited musl64: request65536 +16-byte overhead,
          // rounded to32-byte chunk alignment =65568. Guarded mode differs.
          const uintptr_t a=reinterpret_cast<uintptr_t>(blocks[i-1]);
          const uintptr_t b=reinterpret_cast<uintptr_t>(blocks[i]);
          adjacent=b>a && b-a==65568 ? adjacent+1 : 1;
          if(adjacent>best)best=adjacent;
        }
      }
      if(best>=4)++result.adjacentGroups;
    }
    for(unsigned index=1;index<23;++index)drop(blocks[index]);
    drop(blocks[0]);drop(blocks[23]);
    if(!error && (!matches(left,8192,0x41) || !matches(right,8192,0x72)))error|=2;
    if(!error) {
      unsigned char* splits[4]{};
      const size_t sizes[4]={4096,32768,8192,16384};
      for(unsigned i=0;i<4;++i) {
        splits[i]=alloc(sizes[i]);
        if(!splits[i])error|=4;
        else memset(splits[i],int(0xb0+i),sizes[i]);
      }
      for(unsigned i=0;i<4;++i) {
        if(splits[i] && !matches(splits[i],sizes[i],static_cast<unsigned char>(0xb0+i)))error|=8;
        drop(splits[i]);
      }
      auto* p=alloc(98304);
      if(!p)error|=16;
      else {
        memset(p,0x5c,98304);++result.calls;
        auto* grown=static_cast<unsigned char*>(resize(p,196608));
        if(!grown)error|=32;
        else {
          p=grown;if(!matches(p,98304,0x5c))error|=64;
          ++result.calls;auto* shrunk=static_cast<unsigned char*>(resize(p,127));
          if(!shrunk)error|=128;
          else {p=shrunk;if(!matches(p,127,0x5c))error|=256;}
        }
        drop(p);
      }
      ++result.calls;auto* zeros=static_cast<unsigned char*>(zero(1,196608));
      if(!zeros)error|=512;
      else {if(!matches(zeros,196608,0))error|=1024;drop(zeros);}
      if(!matches(left,8192,0x41) || !matches(right,8192,0x72))error|=2048;
    }
    drop(left);drop(right);
    result.errorMask|=error;
    if(error)break;
    ++result.completed;
  }
  return result;
}
}
