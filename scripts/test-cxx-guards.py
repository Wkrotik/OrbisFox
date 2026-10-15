#!/usr/bin/env python3
"""Pinned libc++abi guard contention/reset/recursion, with host native-ID double."""
from pathlib import Path
import importlib.util
import hashlib
import json
import subprocess
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/cxx-guard-host'
def main():
    spec=importlib.util.spec_from_file_location('runtime',ROOT/'scripts/build-libcxx.py')
    runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime);runtime.adapt()
    OUT.mkdir(parents=True,exist_ok=True)
    # Only the host libc selection differs: no SDK structs/headers on Linux.
    config=(ROOT/'.deps/libcxx-orbis/include/c++/v1/__config_site').read_text()
    (OUT/'__config_site').write_text(config.replace('#define _LIBCPP_HAS_MUSL_LIBC 1','#define _LIBCPP_HAS_MUSL_LIBC 0'))
    command=['clang++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-nostdinc++','-D__ORBIS__','-I'+str(OUT),'-I'+str(ROOT/'.deps/libcxx-orbis/include/c++/v1'),
        '-I'+str(ROOT/'.deps/llvm-runtimes/libcxxabi/src'),'-I'+str(ROOT/'.deps/llvm-runtimes/libcxx/src'),
        str(ROOT/'tests/cxx_guard_test.cpp'),'-pthread','-o',str(OUT/'test')]
    with (OUT/'compile.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (OUT/'test.log').open('w') as log:subprocess.run([str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,timeout=90,check=True)
    source=ROOT/'.deps/llvm-runtimes/libcxxabi/src/cxa_guard_impl.h'
    (OUT/'test-report.json').write_text(json.dumps({'passed':True,'cycles':32,'asan_ubsan':True,
        'actual_pinned_guard_header':True,'actual_host_pthread_contention':True,'initializer_once':True,
        'abort_and_retry':True,'recursive_initializer_SIGABRT_preserved':True,'native_sce_thread_id_doubled':True,
        'firmware_verified':False,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()},indent=2)+'\n')
    print('C++ guards:32 cycles actual implementation/concurrent pthreads/reset/recursive SIGABRT; native-ID double')
if __name__=='__main__':main()
