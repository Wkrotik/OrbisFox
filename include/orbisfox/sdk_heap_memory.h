#pragma once
#include <stddef.h>
namespace orbisfox {
struct SdkHeapMemoryStats {size_t mappings=0,bytes=0;unsigned allocationFailures=0,mapFailures=0;};
void enable_sdk_direct_heap(bool enabled);
void* map_sdk_direct_heap(size_t bytes,int protection);
// 0 means not owned, 1 exact whole mapping, 2 overlapping/partial mapping.
int sdk_direct_heap_ownership(void* address,size_t bytes);
int unmap_sdk_direct_heap(void* address,size_t bytes);
SdkHeapMemoryStats sdk_direct_heap_stats();
}
