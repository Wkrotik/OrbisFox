// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace orbisfox {
// Metadata only: never read caller payloads, unwind frames, or own allocations.
struct AllocatorFlightEvent {
  uint64_t sequence=0,caller=0,input=0,output=0,bytes=0,extra=0,thread=0;
  uint8_t operation=0,phase=0;
  uint16_t depth=0;
  uint32_t checksum=0;
};
static_assert(sizeof(AllocatorFlightEvent)==64);
static_assert(offsetof(AllocatorFlightEvent,checksum)==60);
constexpr uint64_t allocatorFlightMagic=UINT64_C(0x3130544c4658424f); // OBXFLT01
constexpr size_t allocatorFlightCapacity=1048576; // 64 MiB + 64-byte header per run.
inline uint32_t allocator_flight_checksum(const AllocatorFlightEvent& event){
  uint32_t value=2166136261u;const auto* bytes=reinterpret_cast<const unsigned char*>(&event);
  for(size_t i=0;i<offsetof(AllocatorFlightEvent,checksum);++i)value=(value^bytes[i])*16777619u;
  return value;
}
inline uint8_t allocator_flight_operation(const char* name){
  const char* names[]={"internal","malloc","calloc","realloc","free","malloc_usable_size",
    "memalign","__memalign","aligned_alloc","posix_memalign","valloc","__expand_heap",
    "SDK-discard","SDK-unmap","SDK-map","SDK-copy","Mesa-dispatch","fault"};
  for(uint8_t i=0;i<sizeof(names)/sizeof(*names);++i){
    size_t n=0;while(name[n]&&name[n]==names[i][n])++n;
    if(!name[n]&&!names[i][n])return i;
  }
  return 255;
}
// Caller serializes this object with the existing allocator mutex. No new lock
// or heap storage. Batches avoid synchronous per-allocation filesystem traffic.
template<size_t Batch=1024> class AllocatorFlightBuffer {
  static_assert(Batch>0&&Batch<=allocatorFlightCapacity);
  AllocatorFlightEvent events[Batch]{};
  size_t count=0;uint64_t generation=0,sequence=0;
  bool failed=false;
 public:
  bool ioFailed() const {return failed;}
  void discard(){count=0;generation=0;sequence=0;failed=false;}
  template<class Sink> void push(AllocatorFlightEvent event,uint64_t run,Sink sink){
    if(run!=generation){discard();generation=run;}
    event.sequence=++sequence;event.checksum=allocator_flight_checksum(event);events[count++]=event;
    if(count==Batch)flush(sink,false);
  }
  template<class Sink> void flush(Sink sink,bool force){
    if((count||force)&&!sink(events,count,generation,force))failed=true;
    count=0; // Failed batches are explicitly gaps, never reported as persisted.
  }
};
}
