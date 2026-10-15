import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class GCChunkMemoryTests(unittest.TestCase):
    def test_native_chunk_alignment_zeroing_failure_cleanup_and_release(self):
        code=r'''
#include "OrbisGCChunkMemory.h"
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <sys/types.h>
static void* physical=nullptr;static bool failAlloc=false,failMap=false,releasedMapping=false;static unsigned releases=0;
extern "C" size_t sceKernelGetDirectMemorySize(){return 1024*1024*1024;}
extern "C" int32_t sceKernelAllocateDirectMemory(off_t a,off_t end,size_t n,size_t align,int32_t type,off_t* out){assert(a==0&&end==1024*1024*1024&&n==1048576&&align==1048576&&type==0);if(failAlloc)return int32_t(0x8002000c);assert(!physical);assert(posix_memalign(&physical,align,n)==0);memset(physical,0xa7,n);*out=1048576;releasedMapping=false;return 0;}
extern "C" int32_t sceKernelMapDirectMemory(void** p,size_t n,int32_t prot,int32_t flags,off_t off,size_t align){assert(n==1048576&&prot==3&&flags==0&&off==1048576&&align==1048576);if(failMap)return int32_t(0x80020016);*p=physical;return 0;}
extern "C" int32_t sceKernelMunmap(void* p,size_t n){assert(p==physical&&n==1048576);releasedMapping=true;return 0;}
extern "C" int32_t sceKernelReleaseDirectMemory(off_t off,size_t n){assert(off==1048576&&n==1048576&&(releasedMapping||failMap));free(physical);physical=nullptr;++releases;return 0;}
int main(){using namespace orbisfox;
 assert(!map_gc_chunk_memory(65536,65536)&&errno==EINVAL);
 failAlloc=true;assert(!map_gc_chunk_memory(1048576,1048576)&&errno==ENOMEM&&!physical);failAlloc=false;
 failMap=true;assert(!map_gc_chunk_memory(1048576,1048576)&&errno==EINVAL&&!physical&&releases==1);failMap=false;
 void* p=map_gc_chunk_memory(1048576,1048576);assert(p&&uintptr_t(p)%1048576==0);for(size_t i=0;i<1048576;++i)assert(static_cast<unsigned char*>(p)[i]==0);
 auto s=gc_chunk_memory_stats();assert(s.mappings==1&&s.bytes==1048576&&s.allocationFailures==1&&s.mapFailures==1);
 char unrelated;assert(!unmap_gc_chunk_memory(&unrelated,1));assert(physical==p);
 assert(unmap_gc_chunk_memory(p,1048576)&&!physical&&releases==2);
 assert(!unmap_gc_chunk_memory(p,1048576));s=gc_chunk_memory_stats();assert(!s.mappings&&!s.bytes);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'test.cpp').write_text(code)
            subprocess.run(['clang++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(ROOT/'gecko/orbisfox'),str(p/'test.cpp'),str(ROOT/'gecko/orbisfox/OrbisGCChunkMemory.cpp'),'-pthread','-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True,timeout=10)
    def test_only_arena_chunks_use_direct_mapping(self):
        source=(ROOT/'scripts/patch-gecko-layout.py').read_text()
        self.assertIn('MapGCChunkPages(ChunkSize, ChunkSize, stallAndRetry)',source)
        self.assertIn('return MapAlignedPages(length, alignment, retry)',source)
        self.assertNotIn("replace_once(root, 'js/src/gc/BufferAllocator.cpp'",source)
        self.assertIn('unmap_gc_chunk_memory(region, length)',source)
