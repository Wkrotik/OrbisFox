#!/usr/bin/env python3
"""Test the real patched NSPR static linker on host with ASan/UBSan."""
import hashlib,json,os
from pathlib import Path
import subprocess,sys

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/'.deps/gecko-layout/nsprpub'
BUILD=ROOT/'build/nspr-static-host'

def run(args,log,*,cwd=BUILD,env=None):
    with log.open('w') as output:
        subprocess.run(list(map(str,args)),cwd=cwd,env=env,stdout=output,
                       stderr=subprocess.STDOUT,check=True)

def main():
    if '_PR_ORBIS_STATIC_LINKER' not in (SOURCE/'pr/src/linking/prlink.c').read_text():
        raise RuntimeError('Experimental NSPR static-linker patch has not been prepared')
    BUILD.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,CC='clang',CXX='clang++',CPPFLAGS='-D_PR_ORBIS_STATIC_LINKER=1',
             CFLAGS='-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer',
             LDFLAGS='-fsanitize=address,undefined')
    revision='nspr-static-host-asan-ubsan-v1\n'
    stamp=BUILD/'.static-test-revision'
    if not stamp.exists() or stamp.read_text()!=revision or not (BUILD/'Makefile').exists():
        run([SOURCE/'configure','--enable-64bit','--disable-tests','--disable-shared','--enable-static'],
            BUILD/'configure.log',env=env)
        stamp.write_text(revision)
    run(['make','-j4'],BUILD/'build.log',env=env)
    libraries=[BUILD/'pr/src/libnspr4.a',BUILD/'lib/ds/libplds4.a',BUILD/'lib/libc/src/libplc4.a']
    run(['clang++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
         '-I'+str(ROOT/'gecko/orbisfox/native'),'-I'+str(BUILD/'dist/include/nspr'),
         ROOT/'tests/nspr_static_link_test.cpp',ROOT/'gecko/orbisfox/native/nspr_link_probe.cpp',
         '-Wl,--start-group',*libraries,'-Wl,--end-group','-lpthread','-o',BUILD/'behavior-test'],
        BUILD/'behavior-compile.log',cwd=ROOT)
    env=dict(env,ASAN_OPTIONS='detect_leaks=1',UBSAN_OPTIONS='halt_on_error=1')
    run([BUILD/'behavior-test'],BUILD/'behavior-test.log',env=env)
    imports=subprocess.check_output(['llvm-nm','--undefined-only',BUILD/'pr/src/linking/prlink.o'],text=True)
    if any(line.split()[-1] in ('dlopen','dlsym','dlclose','dlerror') for line in imports.splitlines() if line.split()):
        raise RuntimeError('Static NSPR linker still imports a desktop DLL API')
    report={'real_pinned_nspr_source':True,'static_linker_branch_exercised':True,
            'nspr_library_and_behavior_test_asan_ubsan_instrumented':True,
            'initialization_static_dispatch_cache_refcount_unload_cleanup_passed':True,
            'missing_symbols_and_unknown_dlls_rejected':True,'repeated_probe_cycles':32,
            'linker_desktop_dll_imports':[],
            'prlink_source_sha256':hashlib.sha256((SOURCE/'pr/src/linking/prlink.c').read_bytes()).hexdigest(),
            'hardware_tested':False,'scope':'Host NSPR static-linker behavior, not full Gecko/firmware certification'}
    (BUILD/'test-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Real NSPR static-linker initialization/behavior: 32 cycles passed under ASan/UBSan; no desktop DLL imports.')
    return 0

if __name__=='__main__':
    sys.exit(main())
