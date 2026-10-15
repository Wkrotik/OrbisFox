#include "orbisfox/heap_bin_audit.h"
#include <cassert>
#include <array>
#include <cstring>
#include <limits>
using orbisfox::HeapBinAudit;
int main(){
  alignas(16) std::array<unsigned char,HeapBinAudit::stateBytes> state{};
  alignas(16) std::array<unsigned char,512> arena{};
  const auto store=[](unsigned char* p,uint64_t value){std::memcpy(p,&value,8);};
  const uintptr_t base=reinterpret_cast<uintptr_t>(arena.data()),head=base+16,tail=base+160;
  constexpr unsigned bin=63;
  const uintptr_t sentinel=reinterpret_cast<uintptr_t>(state.data())+24*bin;
  const auto setup=[&](bool pair=false){
    state.fill(0);arena.fill(0);
    store(state.data(),UINT64_C(1)<<bin);store(state.data()+16+24*bin,head);store(state.data()+24+24*bin,pair?tail:head);
    store(arena.data()+24,96);store(arena.data()+32,pair?tail:sentinel);store(arena.data()+40,sentinel);store(arena.data()+112,96);
    if(pair){store(arena.data()+168,96);store(arena.data()+176,sentinel);store(arena.data()+184,head);store(arena.data()+256,96);}
  };
  HeapBinAudit audit;assert(!audit.check(state.data()).code);
  // Empty initialized and uninitialized bins, including bit63, are valid.
  store(state.data()+16+24*bin,sentinel);store(state.data()+24+24*bin,sentinel);assert(!audit.check(state.data()).code);
  assert(audit.addArena(arena.data(),arena.size()));setup();
  const auto savedState=state;const auto savedArena=arena;
  assert(!audit.check(state.data()).code);assert(state==savedState && arena==savedArena);
  uint64_t header[4]{};assert(audit.describe(head,header));assert(header[0]==0 && header[1]==96 && header[2]==sentinel && header[3]==sentinel);
  assert(!audit.describe(1,header));assert(header[1]==96);
  setup(true);assert(!audit.check(state.data()).code);
  setup();store(state.data(),0);assert(audit.check(state.data()).code==1);
  setup();store(state.data()+16+24*bin,1);assert(audit.check(state.data()).code==2); // Not dereferenced.
  setup();store(arena.data()+24,97);assert(audit.check(state.data()).code==3);
  setup();store(arena.data()+40,0);assert(audit.check(state.data()).code==4); // Actual hardware null-prev pattern.
  setup();store(arena.data()+32,1);assert(audit.check(state.data()).code==5); // Not dereferenced.
  setup(true);store(arena.data()+184,sentinel);assert(audit.check(state.data()).code==6);
  setup(true);store(arena.data()+32,sentinel);assert(audit.check(state.data()).code==7);
  setup();store(arena.data()+24,UINT64_C(0xffffffffffffffe0));assert(audit.check(state.data()).code==8);
  setup();store(arena.data()+112,97);assert(audit.check(state.data()).code==9);
  // No range, truncated header, and two exactly adjacent registered ranges.
  setup();HeapBinAudit empty;assert(empty.check(state.data()).code==2);
  HeapBinAudit truncated;assert(truncated.addArena(arena.data()+16,31));assert(truncated.check(state.data()).code==2);
  HeapBinAudit adjacent;assert(adjacent.addArena(arena.data(),32));assert(adjacent.addArena(arena.data()+32,480));assert(!adjacent.check(state.data()).code);
  HeapBinAudit gap;assert(gap.addArena(arena.data(),32));assert(gap.addArena(arena.data()+33,479));assert(gap.check(state.data()).code==2);
  assert(!audit.addArena(nullptr,16));assert(!audit.addArena(arena.data(),0));
  assert(!audit.addArena(reinterpret_cast<void*>(UINTPTR_MAX-7),16));
  HeapBinAudit full;for(unsigned i=0;i<128;++i)assert(full.addArena(arena.data(),arena.size()));assert(!full.addArena(arena.data(),arena.size()));
}
