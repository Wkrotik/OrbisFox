#!/usr/bin/env python3
"""Actual native lock wrapper + public OpenOrbis musl bin allocator.
Linux mmap/atomic/thread-flag shims are explicit; not firmware certification.
"""
from pathlib import Path
import subprocess,json,urllib.request,hashlib,os
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/native-allocator-host'
REV='2b0bb8ce2fa64ac255cb656785729d159a5f074c'
HASHES={
 'src/malloc/malloc.c':'d79ce9725eb751a1a052c76e0f711af638c54424fc0fbd5100ec4d79578ec7da',
 'src/internal/malloc_impl.h':'e7ca6e1cb90df8e374668fd2362d6f5a7991e9c9987fb7252ce7b5b7f0af49d6',
 'src/malloc/memalign.c':'c60b21e6691eb4dffb9a710b007e8db4db7799d26702c2366093bfaba0c67174',
 'src/malloc/posix_memalign.c':'d2435683f4a799285eb02df9cdca5a8aff9aa0f45d1ee1a33b595bc5ea401eba',
 'src/malloc/aligned_alloc.c':'3d30c9f7f35878e077f1315a4e8e50048bcbd54cca9c67cc0b7c4c6a8f6a7fa2',
 'src/legacy/valloc.c':'63e11ddeb6e7b1098154fb9f18241d28c0e367047bd7a5862a18ce2ca95f52e9',
 'src/malloc/malloc_usable_size.c':'87ee2b69f5cdbc7e2d6c010db0d2ac5ba407d800ba01459761c835f76a54de1f'}
def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'test-report.json').unlink(missing_ok=True);sources={}
    for name in HASHES:
        target=OUT/Path(name).name
        if not target.exists():
            with urllib.request.urlopen('https://raw.githubusercontent.com/OpenOrbis/musl/'+REV+'/'+name,timeout=20) as r:target.write_bytes(r.read())
        sources[name]=hashlib.sha256(target.read_bytes()).hexdigest()
        if sources[name]!=HASHES[name]:raise ValueError('Pinned allocator source drift: '+name)
    (OUT/'libc.h').write_text('''#pragma once
#include <stddef.h>
#include <malloc.h>
#define hidden
#define SDK_STRING_(x) #x
#define SDK_STRING(x) SDK_STRING_(x)
#define weak_alias(old,new) extern __typeof(old) new __attribute__((weak,alias(SDK_STRING(old))));
#define PAGE_SIZE SDK_TEST_PAGE_SIZE
struct sdk_libc_model {int unused[3];int threads_minus_1;};
extern struct sdk_libc_model sdk_libc;
#define libc sdk_libc
#define __mmap mmap
#define __munmap munmap
#define __mremap sdk_test_mremap
void *sdk_test_mremap(void*,size_t,size_t,int);
#define __madvise madvise
''')
    (OUT/'pthread_impl.h').write_text('''#pragma once
void *__expand_heap(size_t*);
void __wait(volatile int*,volatile int*,int,int);
void __wake(volatile int*,int,int);
''')
    (OUT/'atomic.h').write_text('''#pragma once
#include <stdint.h>
static inline int a_swap(volatile int* p,int v){return __atomic_exchange_n(p,v,__ATOMIC_SEQ_CST);}
static inline void a_store(volatile int* p,int v){__atomic_store_n(p,v,__ATOMIC_SEQ_CST);}
static inline void a_and_64(volatile uint64_t* p,uint64_t v){__atomic_fetch_and(p,v,__ATOMIC_SEQ_CST);}
static inline void a_or_64(volatile uint64_t* p,uint64_t v){__atomic_fetch_or(p,v,__ATOMIC_SEQ_CST);}
static inline int a_ctz_64(uint64_t v){return __builtin_ctzll(v);}
static inline void a_crash(void){__builtin_trap();}
''')
    (OUT/'backend.c').write_text('''#define _GNU_SOURCE
#include <sys/mman.h>
#include <stddef.h>
#include <stdlib.h>
#include <errno.h>
#include "libc.h"
#include "atomic.h"
struct sdk_libc_model sdk_libc={{0,0,0},0};
void sdk_test_thread_flag(int value){sdk_libc.threads_minus_1=value;}
void *sdk_test_mremap(void* p,size_t old,size_t size,int flags){if(getenv("SDK_TEST_MREMAP_ENOSYS")){errno=ENOSYS;return MAP_FAILED;}return mremap(p,old,size,flags);}
// Explicit host model of the installed SDK expand_heap.lo policy: page-round
// and double the minimum arena size after every two successful expansions.
// A request-only mmap shim strands 64KiB chunks in independent small arenas,
// so it cannot cover the reclaim/coalesce path required by the canary probe.
void *__expand_heap(size_t* n){
 static unsigned expansions;
 if(*n>PTRDIFF_MAX-PAGE_SIZE){errno=ENOMEM;return 0;}
 size_t size=(*n+PAGE_SIZE-1)&~(size_t)(PAGE_SIZE-1);
 const size_t minimum=(size_t)PAGE_SIZE<<(expansions/2);
 if(size<minimum)size=minimum;
 void* p=mmap(0,size,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 if(p==MAP_FAILED)return 0;
 *n=size;++expansions;return p;
}
void __wait(volatile int* p,volatile int* w,int v,int priv){(void)p;(void)w;(void)v;(void)priv;__builtin_trap();}
void __wake(volatile int* p,int count,int priv){(void)p;(void)count;(void)priv;__builtin_trap();}
''')
    rename=['malloc','free','realloc','calloc','aligned_alloc','posix_memalign','memalign','valloc','malloc_usable_size','__memalign','__bin_chunk','__malloc_replaced','__malloc_donate']
    cases=[]
    with (OUT/'compile.log').open('w') as log, (OUT/'test.log').open('w') as output:
      for page in (4096,16384):
        objects=[]
        for source in ['malloc.c','memalign.c','posix_memalign.c','aligned_alloc.c','valloc.c','malloc_usable_size.c','backend.c']:
            obj=OUT/(source+'.o');cmd=['clang','-std=c11','-D_GNU_SOURCE=',f'-DSDK_TEST_PAGE_SIZE={page}','-O1','-g','-fsanitize=address,undefined','-Wno-parentheses','-I'+str(OUT),'-include',str(OUT/'libc.h')]+['-D'+name+'=sdk_'+name for name in rename]+['-c',str(OUT/source),'-o',str(obj)]
            if source=='malloc.c':cmd.insert(1,'-Dmemcpy=orbisfox_sdk_realloc_copy')
            subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True);objects.append(str(obj))
        subprocess.run(['clang++','-std=c++20','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-DORBISFOX_FULL_GECKO','-DORBISFOX_SDK_REALLOC_COMPAT','-I'+str(ROOT/'include'),str(ROOT/'tests/native_allocator_test.cpp'),str(ROOT/'src/ps4/native_allocator.cpp'),*objects,'-pthread','-o',str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,check=True)
        for locks in (0,1):
          for unavailable_remap in (False,True):
           for guarded in (False,True):
            env=os.environ.copy()
            if guarded:env['SDK_TEST_HEAP_GUARDS']='1'
            else:env.pop('SDK_TEST_HEAP_GUARDS',None)
            if locks:env['SDK_TEST_BIN_LOCKS']='1'
            else:env.pop('SDK_TEST_BIN_LOCKS',None)
            if unavailable_remap:env['SDK_TEST_MREMAP_ENOSYS']='1'
            else:env.pop('SDK_TEST_MREMAP_ENOSYS',None)
            subprocess.run([str(OUT/'test')],env=env,stdout=output,stderr=subprocess.STDOUT,timeout=90,check=True)
            cases.append({'page_bytes':page,'bin_lock_flag':locks,'mremap_ENOSYS':unavailable_remap,'guarded':guarded,'cycles':2 if guarded else 32,'passed':True})
    (OUT/'test-report.json').write_text(json.dumps({'passed':True,'cycles':32,'workers':8,'actual_native_wrapper':True,'public_OpenOrbis_musl_revision':REV,'sources':sources,'public_revision_not_yet_proven_exact_release_archive_revision':True,'host_matrix':cases,'native_private_flag_writes':False,'large_bin_mmap_boundary_shrink_grow_zeroing_tested':True,'ASan_UBSan_public_allocator_and_wrapper':True,'Linux_mmap_atomic_thread_flag_backend_shims':True,'SDK_geometric_arena_growth_explicit_host_model':True,'raw_reclaim_adjacent_four_chunk_groups_required':True,'raw_boundary_chunk_header_bin_mmap_selection_verified':True,'boundary_requests':[229360,229361,229376],'ownership_counters_patterns_realloc_calloc_alignment_cross_thread_free_and_errors_tested':True,'firmware_tested':False},indent=2)+'\n')
    print('Native heap:32 normal/2 guarded cycles8 threads, actual wrapper + public OpenOrbis musl allocator, 4K/16K pages, skipped/active bin locks, real/ENOSYS mremap; large patterns/realloc/calloc/alignment/handoff/errors PASS; OS shims, not firmware proof')
if __name__=='__main__':main()
