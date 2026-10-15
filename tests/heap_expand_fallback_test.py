import subprocess
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class HeapExpansionTests(unittest.TestCase):
    def test_bounded_real_mapping_retry_and_cursor_scaling(self):
        source=r'''
#include "orbisfox/heap_expand_fallback.h"
#include "orbisfox/cursor_scale.h"
#include <cassert>
#include <cerrno>
#include <limits>
int main(){
 size_t n=2048;unsigned calls=0;
 auto failed=[](size_t*)->void*{errno=ENOMEM;return nullptr;};
 auto first=[&](size_t* bytes)->void*{*bytes=65536;return reinterpret_cast<void*>(0x200000);};
 auto never=[&](size_t)->void*{++calls;assert(false);return nullptr;};
 assert(orbisfox::expand_heap_with_retry(&n,first,never)==reinterpret_cast<void*>(0x200000));assert(n==65536&&calls==0);
 n=2048;auto fits=[&](size_t bytes)->void*{++calls;assert(bytes==4*1024*1024);return reinterpret_cast<void*>(0x400000);};
 assert(orbisfox::expand_heap_with_retry(&n,failed,fits)==reinterpret_cast<void*>(0x400000));assert(n==4*1024*1024&&calls==1);
 n=2048;calls=0;auto onlySmall=[&](size_t bytes)->void*{++calls;if(bytes>16384){errno=ENOMEM;return reinterpret_cast<void*>(UINTPTR_MAX);}return reinterpret_cast<void*>(0x200000);};
 assert(orbisfox::expand_heap_with_retry(&n,failed,onlySmall)==reinterpret_cast<void*>(0x200000));assert(n==16384&&calls==2);
 n=2048;calls=0;auto none=[&](size_t)->void*{++calls;errno=ENOMEM;return reinterpret_cast<void*>(UINTPTR_MAX);};
 assert(!orbisfox::expand_heap_with_retry(&n,failed,none));assert(n==2048&&calls==2&&errno==ENOMEM);
 n=0;calls=0;assert(!orbisfox::expand_heap_with_retry(&n,failed,none));assert(calls==0);
 n=8*1024*1024;calls=0;assert(!orbisfox::expand_heap_with_retry(&n,failed,none));assert(calls==1);
 orbisfox::CursorScale scale;int total=0;for(int i=0;i<4;++i)total+=scale.update(1,0.25);assert(total==1);
 scale.reset();total=0;for(int i=0;i<4;++i)total+=scale.update(-1,0.25);assert(total==-1);
 assert(scale.update(2,3)==6);assert(scale.update(0,1)==0);assert(scale.update(2,std::numeric_limits<double>::quiet_NaN())==2);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'test.cpp').write_text(source)
            subprocess.run(['clang++','-std=c++20','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(ROOT/'include'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True,timeout=10)
