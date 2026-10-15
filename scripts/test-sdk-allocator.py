#!/usr/bin/env python3
"""Exercise installed OpenOrbis allocator object bytes with explicit Linux OS shims.
SDK objects are NOT sanitizer-instrumented; wrapper/harness are. Not firmware proof.
"""
from pathlib import Path
import subprocess,hashlib,json,os,runpy,resource
expose=runpy.run_path(str(Path(__file__).with_name('sdk-heap-audit-object.py')))['expose']
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/sdk-allocator-host'
ARCHIVE=ROOT/'.deps/OpenOrbis/PS4Toolchain/lib/libc.a'
MEMBERS=['malloc.lo','expand_heap.lo','memalign.lo','posix_memalign.lo','aligned_alloc.lo','valloc.lo','malloc_usable_size.lo','memcpy.lo','memset.lo','memmove.lo']
def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'test-report.json').unlink(missing_ok=True);objects=[];hashes={}
    names=['malloc','free','realloc','calloc','aligned_alloc','posix_memalign','memalign','__memalign','valloc','malloc_usable_size','__bin_chunk','__malloc_replaced','__malloc_donate','memcpy','memset','memmove']
    operating={'___errno_location':'sdk_os_errno','__expand_heap':'sdk_os_expand_heap','__libc':'sdk_os_libc','__wait':'sdk_os_wait','__mmap':'sdk_os_mmap','__munmap':'sdk_os_munmap','__mremap':'sdk_os_mremap','__madvise':'sdk_os_madvise'}
    for member in MEMBERS:
        data=subprocess.check_output(['llvm-ar','p',str(ARCHIVE),member]);hashes[member]=hashlib.sha256(data).hexdigest()
        original=OUT/member;original.write_bytes(data);renamed=OUT/(member+'.renamed.o')
        if member=='malloc.lo':
            bad=OUT/'malloc-unpinned-test.lo';bad.write_bytes(data[:-1]+bytes([data[-1]^1]))
            try:expose(bad,OUT/'malloc-unpinned-rejected.o')
            except ValueError as failure:
                assert str(failure)=='Unpinned SDK allocator object; read-only bin audit refused'
            else:raise AssertionError('Audit must refuse unknown allocator object bytes')
            exposed=OUT/'malloc-audited.lo';expose(original,exposed);original=exposed
        command=['llvm-objcopy']
        for old,new in {**{n:'sdk_'+n for n in names},**operating}.items():command+=['--redefine-sym',old+'='+new]
        subprocess.run(command+[str(original),str(renamed)],check=True);objects.append(str(renamed))
    backend=OUT/'sdk-os-shims.cpp'
    backend.write_text('''#define _GNU_SOURCE 1
#include <sys/mman.h>
#include <unistd.h>
#include <cerrno>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <vector>
#include <cassert>
#include <initializer_list>
#include <cstdio>
#include "orbisfox/heap_advice_probe.h"
#include "orbisfox/native_allocator.h"
#include "orbisfox/sdk_heap_memory.h"
static uint64_t reclaimAdviceCalls=0;
extern "C" {
void sdk_test_reclaim_observed(){assert((std::getenv("SDK_TEST_RECLAIM_UNSUPPORTED")||std::getenv("SDK_TEST_DIRECT_BACKING"))?reclaimAdviceCalls==0:reclaimAdviceCalls>0);std::fprintf(stderr,"Installed SDK reclaim VM shim: nonempty16KiB-aligned madvise calls=%llu (Linux, not firmware)\\n",static_cast<unsigned long long>(reclaimAdviceCalls));}
void* sdk_memcpy(void*,const void*,size_t);void* sdk_memset(void*,int,size_t);void* sdk_memmove(void*,const void*,size_t);
void sdk_test_memory_primitives(){
 for(size_t size:{size_t(0),size_t(1),size_t(3),size_t(16),size_t(31),size_t(64),size_t(4095),size_t(4096),size_t(16383),size_t(16384),size_t(65537),size_t(262144),size_t(1048576),size_t(4194304)})
  for(unsigned offset=0;offset<32;++offset){
   std::vector<unsigned char> source(size+128),output(size+128,0xa7),expected=output;
   for(size_t i=0;i<source.size();++i)source[i]=static_cast<unsigned char>(i*73);
   auto* p=output.data()+32+offset;auto* q=expected.data()+32+offset;
   sdk_memset(p,0x51,size);std::memset(q,0x51,size);assert(output==expected);
   sdk_memcpy(p,source.data()+offset,size);std::memcpy(q,source.data()+offset,size);assert(output==expected);
   sdk_memmove(p+1,p,size);std::memmove(q+1,q,size);assert(output==expected);
   sdk_memmove(p,p+1,size);std::memmove(q,q+1,size);assert(output==expected);
  }
}
int sdk_os_getpagesize() noexcept{return 16384;}
#define SDK_BRIDGE(result,name,params,args) result __wrap_##name params; result __wrap_sdk_##name params {return __wrap_##name args;}
SDK_BRIDGE(void*,malloc,(size_t n),(n))
SDK_BRIDGE(void,free,(void* p),(p))
SDK_BRIDGE(void*,calloc,(size_t n,size_t s),(n,s))
SDK_BRIDGE(void*,realloc,(void* p,size_t n),(p,n))
SDK_BRIDGE(void*,aligned_alloc,(size_t a,size_t n),(a,n))
SDK_BRIDGE(int,posix_memalign,(void** p,size_t a,size_t n),(p,a,n))
SDK_BRIDGE(void*,memalign,(size_t a,size_t n),(a,n))
SDK_BRIDGE(void*,__memalign,(size_t a,size_t n),(a,n))
SDK_BRIDGE(void*,valloc,(size_t n),(n))
SDK_BRIDGE(size_t,malloc_usable_size,(void* p),(p))
#undef SDK_BRIDGE
void* __wrap___expand_heap(size_t*);
void* __real_sdk_os_expand_heap(size_t*);
void* __wrap_sdk_os_expand_heap(size_t* n){return __wrap___expand_heap(n);}
void* __real___expand_heap(size_t* n){
 static bool injected=false;
 if(!injected && getenv("SDK_TEST_FORCE_EXPAND_FAILURE")){injected=true;errno=ENOMEM;return nullptr;}
 return __real_sdk_os_expand_heap(n);
}
int __wrap___madvise(void*,size_t,int);
int __real_sdk_os_madvise(void*,size_t,int);
int __wrap_sdk_os_madvise(void* p,size_t n,int advice){return __wrap___madvise(p,n,advice);}
int __real___madvise(void* p,size_t n,int advice){return __real_sdk_os_madvise(p,n,advice);}
int __wrap___munmap(void*,size_t);
int __real_sdk_os_munmap(void*,size_t);
int __wrap_sdk_os_munmap(void* p,size_t n){return __wrap___munmap(p,n);}
int __real___munmap(void* p,size_t n){return __real_sdk_os_munmap(p,n);}
int sdk_os_libc[64]{};
void sdk_test_thread_flag(int value){sdk_os_libc[3]=value;}
int* sdk_os_errno(){return &errno;}
void sdk_os_wait(volatile int*,volatile int*,int,int){__builtin_trap();}
void* sdk_os_mmap(void* desired,size_t size,int prot,int flags,int fd,long offset);
void* __wrap___mmap(void*,size_t,int,int,int,off_t);
void* __real_sdk_os_mmap(void*,size_t,int,int,int,long);
void* __wrap_sdk_os_mmap(void* p,size_t n,int prot,int flags,int fd,long off){return __wrap___mmap(p,n,prot,flags,fd,off);}
void* __real___mmap(void* p,size_t n,int prot,int flags,int fd,off_t off){return __real_sdk_os_mmap(p,n,prot,flags,fd,off);}
void* __mmap(void* desired,size_t size,int prot,int flags,int fd,long offset){return __wrap___mmap(desired,size,prot,flags,fd,offset);}
struct DirectPhysical {void* memory=nullptr;size_t bytes=0;bool unmapped=false;};
static DirectPhysical directPhysical[1024];
size_t sceKernelGetDirectMemorySize(){return size_t(4)*1024*1024*1024;}
int32_t sceKernelAllocateDirectMemory(off_t,off_t,size_t n,size_t,int32_t memoryType,off_t* offset){
 assert(memoryType==0); // CPU write-back Onion, never WC graphics heap.
 for(size_t i=0;i<1024;++i)if(!directPhysical[i].memory){void* p=__real_sdk_os_mmap(nullptr,n,3,0x1002,-1,0);if(p==MAP_FAILED)return int32_t(0x8002000c);directPhysical[i]={p,n,false};*offset=off_t(i*16384);return 0;}
 return int32_t(0x8002000c);
}
int32_t sceKernelMapDirectMemory(void** p,size_t n,int32_t,int32_t,off_t offset,size_t){auto& m=directPhysical[size_t(offset)/16384];assert(m.memory&&m.bytes==n);*p=m.memory;return 0;}
int32_t sceKernelMunmap(void* p,size_t n){for(auto& m:directPhysical)if(m.memory==p){assert(m.bytes==n);const int rc=__real_sdk_os_munmap(p,n);if(!rc)m.unmapped=true;return rc?int32_t(0x80020016):0;}return int32_t(0x80020016);}
int32_t sceKernelReleaseDirectMemory(off_t offset,size_t n){auto& m=directPhysical[size_t(offset)/16384];assert(m.memory&&m.bytes==n&&m.unmapped);m={};return 0;}
void* sdk_os_mmap(void* desired,size_t size,int prot,int flags,int fd,long offset){
 // SDK anonymous flag0x1000 is FreeBSD, not Linux0x20. Model16KiB backing
 // alignment, without exporting any shim into the PS4 build.
 if(desired || fd!=-1 || offset || !(flags&0x1000)){errno=EINVAL;return MAP_FAILED;}
 size=(size+16383)&~size_t(16383);const size_t total=size+16384;
 void* p=mmap(nullptr,total,prot,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);if(p==MAP_FAILED)return p;
 const uintptr_t base=reinterpret_cast<uintptr_t>(p),aligned=(base+16383)&~uintptr_t(16383);
 const size_t head=aligned-base,tail=total-head-size;
 if(head)munmap(p,head);if(tail)munmap(reinterpret_cast<void*>(aligned+size),tail);return reinterpret_cast<void*>(aligned);
}
int sdk_os_munmap(void* p,size_t size){return munmap(p,size);}
int sdk_os_madvise(void* p,size_t size,int advice){
 if(size){assert(reinterpret_cast<uintptr_t>(p)%16384==0 && size%16384==0);++reclaimAdviceCalls;}
 return madvise(p,size,advice);
}
void sdk_test_advice_gate(){
 // Unsupported default never reaches the backend and reports an actual error.
 errno=0;assert(__wrap___madvise(nullptr,16384,4)==-1 && errno==ENOTSUP && reclaimAdviceCalls==0);
 const auto result=orbisfox::probe_heap_advice(16384,
   [](size_t n){return sdk_os_mmap(nullptr,n,3,0x1002,-1,0);},
   [](void* p,size_t n){return sdk_os_madvise(p,n,4);},
   [](void* p,size_t n){return sdk_os_munmap(p,n);});
 assert(result.safe());reclaimAdviceCalls=0;
 orbisfox::configure_native_allocator_reclaim(!std::getenv("SDK_TEST_RECLAIM_UNSUPPORTED"));
 orbisfox::enable_sdk_direct_heap(std::getenv("SDK_TEST_DIRECT_BACKING")!=nullptr);
}
void* sdk_os_mremap(void* p,size_t old,size_t size,int flags){
 if(std::getenv("SDK_TEST_MREMAP_ENOSYS")){errno=ENOSYS;return MAP_FAILED;}
 return mremap(p,old,size,flags);
}
}
''')
    with (OUT/'compile.log').open('w') as log:
        command=['clang++','-std=c++20','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-DORBISFOX_FULL_GECKO','-DORBISFOX_SDK_BIN_AUDIT','-DORBISFOX_INSTALLED_SDK_OBJECTS','-DORBISFOX_NATIVE_DIRECT_HEAP','-DSDK_TEST_NESTED_LINK','-Dgetpagesize=sdk_os_getpagesize','-I'+str(ROOT/'include'),str(ROOT/'tests/native_allocator_test.cpp'),str(ROOT/'src/ps4/native_allocator.cpp'),str(ROOT/'src/ps4/sdk_heap_memory.cpp'),str(backend),*objects,*['-Wl,--wrap=sdk_'+name for name in ['malloc','free','calloc','realloc','aligned_alloc','posix_memalign','memalign','__memalign','valloc','malloc_usable_size']],'-Wl,--wrap=sdk_os_expand_heap','-Wl,--wrap=sdk_os_madvise','-Wl,--wrap=sdk_os_munmap','-Wl,--wrap=sdk_os_mmap','-pthread','-o',str(OUT/'sdk-test')]
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        source=(ROOT/'src/ps4/native_allocator.cpp').read_text()
        marker='if(bytes>capacity){bytes=capacity;++reallocCopyClamps;}'
        assert source.count(marker)==1
        reference=OUT/'native_allocator_unfixed_reference.cpp'
        reference.write_text(source.replace(marker,'/* Unfixed reference: original SDK copy length. */'))
        original_command=[str(reference) if p==str(ROOT/'src/ps4/native_allocator.cpp') else str(OUT/'sdk-test-unfixed') if p==str(OUT/'sdk-test') else p for p in command]
        subprocess.run(original_command,stdout=log,stderr=subprocess.STDOUT,check=True)
    reference_env=os.environ.copy()
    reference_env['SDK_TEST_MREMAP_ENOSYS']='1';reference_env['SDK_TEST_ONLY_MAPPED_SHRINK']='1'
    for key in ['SDK_TEST_HEAP_GUARDS','SDK_TEST_RECLAIM_UNSUPPORTED']:reference_env.pop(key,None)
    def no_core():resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    with (OUT/'unfixed-mapped-shrink.log').open('w') as log:
        reference_result=subprocess.run([str(OUT/'sdk-test-unfixed')],env=reference_env,stdout=log,stderr=subprocess.STDOUT,timeout=30,preexec_fn=no_core)
    if reference_result.returncode==0:raise AssertionError('Unfixed SDK mapped-shrink reference unexpectedly passed')
    assert 'SDK mapped shrink exact regression: begin262144->50201' in (OUT/'unfixed-mapped-shrink.log').read_text()
    with (OUT/'fixed-mapped-shrink.log').open('w') as log:
        subprocess.run([str(OUT/'sdk-test')],env=reference_env,stdout=log,stderr=subprocess.STDOUT,timeout=30,check=True)
    cases=[]
    with (OUT/'test.log').open('w') as log:
      for flag in (0,1):
        for unavailable in (False,True):
           for guarded in (False,True):
            env=os.environ.copy()
            if guarded:env['SDK_TEST_HEAP_GUARDS']='1'
            else:env.pop('SDK_TEST_HEAP_GUARDS',None)
            for key,enabled in [('SDK_TEST_BIN_LOCKS',flag),('SDK_TEST_MREMAP_ENOSYS',unavailable)]:
                if enabled:env[key]='1'
                else:env.pop(key,None)
            for rejected in (False,True):
                if rejected:env['SDK_TEST_RECLAIM_UNSUPPORTED']='1'
                else:env.pop('SDK_TEST_RECLAIM_UNSUPPORTED',None)
                subprocess.run([str(OUT/'sdk-test')],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=90,check=True)
                cases.append({'mock_bin_lock_flag':flag,'Linux_mremap_or_ENOSYS':unavailable,'guarded':guarded,'reclaim_rejected_ENOTSUP':rejected,'cycles':2 if guarded else 32,'audit_mode':'full startup then targeted realloc/copy/discard','passed':True})
    report={'passed':True,'installed_SDK_archive':str(ARCHIVE.relative_to(ROOT)),'object_hashes':hashes,'cycles_per_case':32,'threads':8,'cases':cases,'actual_installed_SDK_allocator_and_memcpy_memset_memmove_objects':True,'actual_SDK_heap_expansion_object_including_geometric_growth':True,'raw_reclaim_coalesce_pretrim_canary_32_rounds_with_adjacent_four_chunk_runs':True,'raw_boundary_chunk_header_bin_mmap_selection_verified':True,'boundary_requests':[229360,229361,229376],'nonempty16KiB_aligned_reclaim_madvise_observed_on_Linux':True,'SDK_objects_not_ASan_instrumented':True,'read_only_endpoint_bin_audit_full_startup_then_targeted_realloc_copy_discard':True,'mapped_free_unmap_leaf_audit':True,'reclaim_retention_gate_host_verified':True,'reclaim_admitted_and_rejected_with_real_ENOTSUP_cases':True,'audit_unpinned_allocator_object_refused':True,'SDK_allocator_allocated_sections_unchanged_by_audit_symbol_exposure':True,'actual_SDK_memory_primitive_padded_unaligned_overlapping_canaries':True,'wrapper_and_harness_ASan_UBSan':True,'Linux16K_mmap_and_errno_wait_flag_shims_explicit':True,'model_private_field_writes_not_native':True,'nested_actual_SDK_malloc_free_realloc_memalign_bridges_match_production_wrap_semantics':True,'guarded_and_raw_modes_tested':True,'firmware_tested':False,'whole_Gecko_site_stability_not_proven':True}
    forced_env=os.environ.copy();forced_env['SDK_TEST_FORCE_EXPAND_FAILURE']='1';forced_env['SDK_TEST_MREMAP_ENOSYS']='1'
    for key in ['SDK_TEST_HEAP_GUARDS','SDK_TEST_ONLY_MAPPED_SHRINK','SDK_TEST_RECLAIM_UNSUPPORTED']:forced_env.pop(key,None)
    with (OUT/'forced-arena-failure.log').open('w') as log:
        subprocess.run([str(OUT/'sdk-test')],env=forced_env,stdout=log,stderr=subprocess.STDOUT,timeout=90,check=True)
    assert 'SDK ARENA RETRY:' in (OUT/'forced-arena-failure.log').read_text()
    direct_env=forced_env.copy();direct_env.pop('SDK_TEST_FORCE_EXPAND_FAILURE',None);direct_env['SDK_TEST_DIRECT_BACKING']='1'
    with (OUT/'direct-backing.log').open('w') as log:
        subprocess.run([str(OUT/'sdk-test')],env=direct_env,stdout=log,stderr=subprocess.STDOUT,timeout=90,check=True)
    report['SDK_direct_backing_actual_allocator_whole_unmap_copy_canaries_passed']=True
    report['SDK_direct_backing_Linux_native_API_doubles_not_firmware_proof']=True
    report['failed_SDK_arena_reservation_real_mapping_retry_passed']=True
    report['mremap_ENOSYS_mapped_shrink_262144_to_50201_regression_fixed']=True
    report['unfixed_reference_returncode']=reference_result.returncode
    report['unfixed_reference_failed_and_fixed_passed_same_SDK_bytes']=True
    (OUT/'test-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Installed SDK heap objects:32 normal/2 guarded cycles8 workers per flag/remap case with nested original SDK calls; large realloc/zero/alignment/handoff PASS. Linux OS shims, SDK objects unsanitized; not firmware/Gecko stability proof')
if __name__=='__main__':main()
