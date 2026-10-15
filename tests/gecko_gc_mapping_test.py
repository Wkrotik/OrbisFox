import subprocess
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class GcMappingTests(unittest.TestCase):
    def test_actual_random_mapping_function_rejects_failed_mapping(self):
        source=(ROOT/'.deps/gecko-layout/js/src/gc/Memory.cpp').read_text()
        start=source.index('static void* MapAlignedPagesRandom(size_t length, size_t alignment) {')
        body=start;depth=0
        for end in range(source.index('{',start),len(source)):
            if source[end]=='{':depth+=1
            if source[end]=='}':
                depth-=1
                if depth==0:break
        fixed=source[body:end+1]
        self.assertIn('defined(__FreeBSD__) && !defined(MOZ_WIDGET_ORBIS)',fixed)
        original=fixed.replace('MapAlignedPagesRandom','UnfixedMapAlignedPagesRandom').replace('defined(__FreeBSD__) && !defined(MOZ_WIDGET_ORBIS)','defined(__FreeBSD__)')
        prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <stdexcept>
#define MOZ_WIDGET_ORBIS 1
#define __FreeBSD__ 1
#define MOZ_ASSERT(x) assert(x)
#define MOZ_CRASH(x) throw std::runtime_error(x)
#define MAP_PRIVATE 2
#define MAP_ANON 0x1000
#define MAP_ALIGNED(n) ((n)<<24)
static constexpr uint64_t minValidAddress=0x200000,hugeSplit=0x7fffffff,maxValidAddress=0x7ffffffff;
static constexpr size_t HugeAllocationSize=1<<30;
static unsigned numAddressBits=35,rawCalls=0,unmapCalls=0,fuzzyCalls=0;
static bool oom=false,failHints=false;
namespace mozilla {static int CeilingLog2Size(size_t){return 20;}}
enum class PageAccess {ReadWrite=3};
static uint64_t GetNumberInRange(uint64_t low,uint64_t){return low;}
static void* MozTaggedAnonymousMmap(void*,size_t,int,int,int,int,const char*){++rawCalls;return reinterpret_cast<void*>(UINTPTR_MAX);}
static void* MapMemoryAtFuzzy(void*,size_t){++fuzzyCalls;return (oom||failHints)?nullptr:reinterpret_cast<void*>(0x21000000);}
static void* MapMemory(size_t){return oom?nullptr:reinterpret_cast<void*>(0x21000000);}
static bool IsInvalidRegion(void* p,size_t){return reinterpret_cast<uintptr_t>(p)>maxValidAddress;}
static void UnmapInternal(void* p,size_t){++unmapCalls;if(p==reinterpret_cast<void*>(UINTPTR_MAX))throw std::runtime_error("invalid unmap");}
static size_t OffsetFromAligned(void* p,size_t alignment){return reinterpret_cast<uintptr_t>(p)%alignment;}
template<bool> static bool TryToAlignChunk(void**,void**,size_t,size_t){return false;}
static void* MapAlignedPagesSlow(size_t,size_t){return nullptr;}
'''
        suffix=r'''
int main(){
 try {UnfixedMapAlignedPagesRandom(1<<20,1<<20);assert(false);} catch(const std::runtime_error&){}
 assert(rawCalls==1 && unmapCalls==1);rawCalls=unmapCalls=0;
 assert(MapAlignedPagesRandom(1<<20,1<<20)==reinterpret_cast<void*>(0x21000000));
 assert(rawCalls==0 && unmapCalls==0);
 failHints=true;fuzzyCalls=0;
 assert(MapAlignedPagesRandom(1<<20,1<<20)==reinterpret_cast<void*>(0x21000000));assert(fuzzyCalls==15);
 oom=true;fuzzyCalls=0;assert(!MapAlignedPagesRandom(1<<20,1<<20));assert(fuzzyCalls==15);
 assert(rawCalls==0 && unmapCalls==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'test.cpp').write_text(prefix+fixed+'\n'+original+suffix)
            result=subprocess.run(['clang++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.cpp'),'-o',str(p/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(p/'test')],check=True,timeout=10)
