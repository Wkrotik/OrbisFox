import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class SdkHeapMemoryTests(unittest.TestCase):
    def test_direct_mapping_zeroing_exact_release_and_failures(self):
        code=r'''
#include "orbisfox/sdk_heap_memory.h"
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <sys/types.h>
static void* physical=nullptr;static bool failAllocate=false,failMap=false,unmapped=false;static unsigned releases=0;
extern "C" size_t sceKernelGetDirectMemorySize(){return 1024*1024*1024;}
extern "C" int32_t sceKernelAllocateDirectMemory(off_t a,off_t b,size_t n,size_t align,int32_t type,off_t* out){assert(a==0&&b==1024*1024*1024&&align==16384&&type==0);if(failAllocate)return int32_t(0x8002000c);assert(!physical);assert(posix_memalign(&physical,align,n)==0);memset(physical,0xa5,n);*out=16384;unmapped=false;return 0;}
extern "C" int32_t sceKernelMapDirectMemory(void** p,size_t,int32_t prot,int32_t flags,off_t o,size_t align){assert(prot==3&&flags==0&&o==16384&&align==16384);if(failMap)return int32_t(0x80020016);*p=physical;return 0;}
extern "C" int32_t sceKernelMunmap(void* p,size_t n){assert(p==physical&&n==65536);unmapped=true;return 0;}
extern "C" int32_t sceKernelReleaseDirectMemory(off_t o,size_t){assert(o==16384&&(unmapped||failMap));free(physical);physical=nullptr;++releases;return 0;}
int main(){using namespace orbisfox;
 assert(map_sdk_direct_heap(65536,3)==reinterpret_cast<void*>(UINTPTR_MAX));assert(errno==ENOTSUP);
 enable_sdk_direct_heap(true);assert(map_sdk_direct_heap(1,3)==reinterpret_cast<void*>(UINTPTR_MAX));assert(errno==EINVAL);
 failAllocate=true;assert(map_sdk_direct_heap(65536,3)==reinterpret_cast<void*>(UINTPTR_MAX));assert(errno==ENOMEM&&!physical);failAllocate=false;
 failMap=true;assert(map_sdk_direct_heap(65536,3)==reinterpret_cast<void*>(UINTPTR_MAX));assert(errno==EINVAL&&!physical&&releases==1);failMap=false;
 void* p=map_sdk_direct_heap(65536,3);assert(p!=reinterpret_cast<void*>(UINTPTR_MAX));for(size_t i=0;i<65536;++i)assert(static_cast<unsigned char*>(p)[i]==0);
 assert(sdk_direct_heap_ownership(p,65536)==1);assert(sdk_direct_heap_ownership(p,16384)==2);assert(sdk_direct_heap_ownership(static_cast<char*>(p)+16384,16384)==2);
 assert(unmap_sdk_direct_heap(p,16384)==-1&&errno==EINVAL);assert(physical==p&&releases==1);
 auto s=sdk_direct_heap_stats();assert(s.mappings==1&&s.bytes==65536&&s.allocationFailures==1&&s.mapFailures==1);
 assert(unmap_sdk_direct_heap(p,65536)==0);assert(!physical&&releases==2);assert(sdk_direct_heap_ownership(p,65536)==0);
 s=sdk_direct_heap_stats();assert(!s.bytes&&!s.mappings);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'test.cpp').write_text(code)
            subprocess.run(['clang++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(ROOT/'include'),str(p/'test.cpp'),str(ROOT/'src/ps4/sdk_heap_memory.cpp'),'-pthread','-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True,timeout=10)
