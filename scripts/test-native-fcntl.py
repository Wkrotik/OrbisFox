#!/usr/bin/env python3
"""Actual full-Gecko file-lock adapter with explicit SDK/resident firmware doubles."""
import hashlib,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
BUILD=ROOT/'build/native-fcntl-host'
def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    (BUILD/'orbis').mkdir(exist_ok=True)
    (BUILD/'orbis/libkernel.h').write_text('''#pragma once
#include <stddef.h>
#include <stdint.h>
using OrbisKernelModule=int;
struct OrbisKernelModuleInfo {size_t size;char name[256];};
#define ORBIS_KERNEL_PROT_CPU_EXEC 4
int sceKernelGetModuleList(OrbisKernelModule*,size_t,size_t*);
int sceKernelGetModuleInfo(OrbisKernelModule,OrbisKernelModuleInfo*);
int sceKernelDlsym(OrbisKernelModule,const char*,void**);
int sceKernelQueryMemoryProtection(const void*,void**,void**,int32_t*);
''')
    (BUILD/'fcntl.h').write_text('''#pragma once
#include_next <fcntl.h>
// Host Linux flock layout matches SDK; rename only its lock command numbers.
#undef F_GETLK
#undef F_SETLK
#undef F_SETLKW
#define F_GETLK 11
#define F_SETLK 12
#define F_SETLKW 13
''')
    source=ROOT/'src/ps4/native_fcntl.cpp'
    shutil.copyfile(source,BUILD/'actual-native-fcntl.inc')
    binary=BUILD/'native-fcntl-test'
    with (BUILD/'compile.log').open('w') as log:
        subprocess.run(['clang++','-std=c++20','-O1','-g','-fsanitize=address,undefined',
            '-fno-omit-frame-pointer','-pthread','-I'+str(BUILD),'-I'+str(ROOT/'include'),
            str(ROOT/'tests/native_fcntl_test.cpp'),'-o',str(binary)],stdout=log,stderr=subprocess.STDOUT,check=True)
    subprocess.run([str(binary)],check=True,timeout=30)
    inactive=BUILD/'non-full-gecko-empty.o'
    subprocess.run(['clang++','-c',str(source),'-o',str(inactive)],check=True)
    assert not subprocess.check_output(['llvm-nm','-g','--defined-only',str(inactive)],text=True).strip()
    (BUILD/'test-report.json').write_text(json.dumps({'passed':True,'cycles':32,'asan_ubsan':True,
        'actual_adapter_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'explicit_sdk_frontend_and_module_and_firmware_doubles':True,'nonlock_arguments_preserved':True,
        'concurrent_once_binding_and_readonly_failure_output_and_overflow_guards_verified':True,
        'non_full_gecko_object_has_no_defined_symbols':True,
        'firmware_locks_or_contention_or_persistent_sqlite_verified':False},indent=2)+'\n')
    print('Actual file-lock adapter: layout/type marshalling, GETLK reverse mapping, real errors, guarded output, non-lock passthrough, bind failure/concurrency, startup comparison, 32 ASan/UBSan cycles PASS (SDK/firmware doubles)')
if __name__=='__main__':main()
