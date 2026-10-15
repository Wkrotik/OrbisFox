#pragma once
#include <stddef.h>
#include <stdint.h>
namespace orbisfox {
// Only SpiderMonkey arena/nursery chunks. Not large shrinkable buffers,
// file mappings, stacks, executable code, or the public mmap implementation.
void* map_gc_chunk_memory(size_t bytes,size_t alignment);
bool unmap_gc_chunk_memory(void* address,size_t bytes);
struct GCChunkMemoryStats {size_t mappings,bytes;uint64_t allocationFailures,mapFailures;};
GCChunkMemoryStats gc_chunk_memory_stats();
}
