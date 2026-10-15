#pragma once
#include <stddef.h>
#include <stdint.h>
namespace orbisfox {
struct HeapAdviceResult {
  unsigned completed=0,errorMask=0;size_t failedSpan=0,failedOffset=0;int adviceResult=0;
  unsigned char actual=0,expected=0;
  bool safe() const {return completed==3 && errorMask==0;}
};
// Test the property SDK free-page reclaim requires: advising an interior range
// must preserve every byte outside that range. No assumption that advised bytes
// immediately become zero (BSD may treat advice as a hint). Own isolated maps;
// no advice is issued against application allocations by this probe.
template<class Map,class Advice,class Unmap>
HeapAdviceResult probe_heap_advice(size_t page,Map map,Advice advice,Unmap unmap){
  HeapAdviceResult result;
  if(page!=16384){result.errorMask=1;return result;}
  const size_t pages[]={16,256,512};
  for(size_t count:pages){
    const size_t bytes=count*page;void* mapping=map(bytes);
    if(!mapping || mapping==reinterpret_cast<void*>(UINTPTR_MAX)){result.errorMask|=2;return result;}
    auto* p=static_cast<volatile unsigned char*>(mapping);
    if(reinterpret_cast<uintptr_t>(mapping)%page){result.errorMask|=1;}
    for(unsigned trial=0;trial<2 && !result.errorMask;++trial){
      const unsigned char pattern=trial?0xa7:0x5d;
      for(size_t i=0;i<bytes;++i)p[i]=pattern;
      const size_t offset=trial?2*page:(count/2)*page,length=trial?bytes-4*page:page;
      const int rc=advice(static_cast<unsigned char*>(mapping)+offset,length);result.adviceResult=rc;
      if(rc){result.errorMask|=4;result.failedSpan=bytes;break;}
      for(size_t i=0;i<bytes;++i){
        if(i>=offset && i-offset<length)continue;
        if(p[i]!=pattern){result.errorMask|=8;result.failedSpan=bytes;result.failedOffset=i;result.actual=p[i];result.expected=pattern;break;}
      }
    }
    if(unmap(mapping,bytes))result.errorMask|=16;
    if(result.errorMask)return result;
    ++result.completed;
  }
  return result;
}
}
