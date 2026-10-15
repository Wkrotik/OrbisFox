#pragma once
#include <stddef.h>
#include <stdint.h>
namespace orbisfox {
// Keep SDK ownership. If its geometrically enlarged arena cannot be mapped,
// retry a bounded real arena, then exactly the page-rounded original request.
// A failed 128MiB reservation must not turn a fulfillable 2KiB request into OOM.
template<class Expand,class Map>
void* expand_heap_with_retry(size_t* bytes,Expand expand,Map map){
  if(!bytes || !*bytes || *bytes>static_cast<size_t>(PTRDIFF_MAX)-16383)return nullptr;
  const size_t needed=(*bytes+16383)&~size_t(16383);
  void* p=expand(bytes);
  if(p && p!=reinterpret_cast<void*>(UINTPTR_MAX))return p;
  const size_t bounded=needed>4*1024*1024?needed:4*1024*1024;
  p=map(bounded);
  if(p && p!=reinterpret_cast<void*>(UINTPTR_MAX)){*bytes=bounded;return p;}
  if(bounded!=needed){
    p=map(needed);
    if(p && p!=reinterpret_cast<void*>(UINTPTR_MAX)){*bytes=needed;return p;}
  }
  return nullptr;
}
}
