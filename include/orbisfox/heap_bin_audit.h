#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace orbisfox {
// Read-only view of the pinned SDK musl64 allocator: binmap, 64 x 24-byte
// bins, two free-lock words. Production binding verifies symbol size and
// unchanged allocator code bytes. Call only while serialized, at outer API
// boundaries or quiescent SDK copy/discard points with bin updates complete.
class HeapBinAudit {
 public:
  static constexpr size_t stateBytes=1552;
  struct Failure { unsigned code=0,bin=0;uintptr_t chunk=0;uint64_t actual=0,expected=0; };
  bool addArena(void* base,size_t size) {
    const uintptr_t start=reinterpret_cast<uintptr_t>(base);
    if(!start || !size || size>UINTPTR_MAX-start || count==128)return false;
    arenas[count++]={start,start+size};return true;
  }
  size_t arenaCount() const {return count;}
  bool describe(uintptr_t chunk,uint64_t (&words)[4]) const {
    if(!contains(chunk,32))return false;
    for(unsigned i=0;i<4;++i)words[i]=word(reinterpret_cast<const unsigned char*>(chunk)+i*8);
    return true;
  }
  // No following of arbitrary corrupted pointers: every chunk/header read
  // must be wholly inside a successfully registered SDK heap expansion.
  Failure check(const unsigned char* state) const {
    const uint64_t map=word(state);
    for(unsigned i=0;i<64;++i) {
      const uintptr_t sentinel=reinterpret_cast<uintptr_t>(state)+24*i;
      const uintptr_t head=word(state+16+24*i),tail=word(state+24+24*i);
      const bool populated=bool(map&(UINT64_C(1)<<i));
      if(!head && !tail && !populated)continue; // Uninitialized empty bin.
      if(head==sentinel && tail==sentinel && !populated)continue;
      if(!populated || !head || !tail || head==sentinel || tail==sentinel)
        return {1,i,head,map,UINT64_C(1)<<i};
      for(unsigned end=0;end<2;++end) {
        const uintptr_t p=end?tail:head;
        if(!contains(p,32))return {2,i,p,0,32};
        const auto* bytes=reinterpret_cast<const unsigned char*>(p);
        const uint64_t size=word(bytes+8),next=word(bytes+16),prev=word(bytes+24);
        if(size<32 || size%32)return {3,i,p,size,32}; // Free, aligned chunk size.
        if((end?next:prev)!=sentinel)return {4,i,p,end?next:prev,sentinel};
        const uintptr_t neighbor=end?prev:next;
        if(neighbor!=sentinel) {
          if(!contains(neighbor,32))return {5,i,p,neighbor,32};
          const uint64_t reciprocal=word(reinterpret_cast<const unsigned char*>(neighbor)+(end?16:24));
          if(reciprocal!=p)return {6,i,p,reciprocal,p};
        } else if(head!=tail)return {7,i,p,neighbor,end?head:tail};
        if(size>UINTPTR_MAX-p || !contains(p+size,16))return {8,i,p,size,0};
        const uint64_t footer=word(reinterpret_cast<const unsigned char*>(p+size));
        if(footer!=size)return {9,i,p,footer,size};
      }
    }
    return {};
  }
 private:
  struct Arena {uintptr_t begin,end;};Arena arenas[128]{};size_t count=0;
  static uint64_t word(const unsigned char* p) {uint64_t value;memcpy(&value,p,8);return value;}
  bool contains(uintptr_t p,size_t bytes) const {
    if(!p || bytes>UINTPTR_MAX-p)return false;
    // Headers may straddle two adjacent expansions coalesced by SDK malloc.
    const uintptr_t limit=p+bytes;uintptr_t covered=p;
    while(covered<limit) {
      uintptr_t next=covered;
      for(size_t i=0;i<count;++i)if(arenas[i].begin<=covered && arenas[i].end>next)next=arenas[i].end;
      if(next==covered)return false;
      covered=next;
    }
    return true;
  }
};
static_assert(HeapBinAudit::stateBytes==8+64*24+8);
}
