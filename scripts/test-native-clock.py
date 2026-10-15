#!/usr/bin/env python3
"""Sanitize actual full-Gecko clock adapter with explicit module/firmware doubles."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build/native-clock-host'
def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    shim = BUILD / 'orbis/libkernel.h'
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text('''#pragma once
#include <stddef.h>
#include <stdint.h>
using OrbisKernelModule = int;
struct OrbisKernelModuleInfo { size_t size; char name[256]; };
#define ORBIS_KERNEL_PROT_CPU_EXEC 4
int sceKernelGetModuleList(OrbisKernelModule*, size_t, size_t*);
int sceKernelGetModuleInfo(OrbisKernelModule, OrbisKernelModuleInfo*);
int sceKernelDlsym(OrbisKernelModule, const char*, void**);
int sceKernelQueryMemoryProtection(const void*, void**, void**, int32_t*);
''')
    source = ROOT / 'src/ps4/native_clock.cpp'
    shutil.copyfile(source, BUILD / 'actual-native-clock.inc')
    binary = BUILD / 'native-clock-test'
    command = ['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
               '-fno-omit-frame-pointer', '-pthread', '-I' + str(BUILD),
               '-I' + str(ROOT / 'include'), str(ROOT / 'tests/native_clock_test.cpp'), '-o', str(binary)]
    with (BUILD / 'compile.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    subprocess.run([str(binary)], check=True, timeout=30)
    inactive = BUILD / 'non-full-gecko-empty.o'
    subprocess.run(['clang++', '-std=c++20', '-c', str(source), '-o', str(inactive)], check=True)
    symbols = subprocess.check_output(['llvm-nm', '-g', '--defined-only', str(inactive)], text=True)
    if symbols.strip(): raise ValueError('Clock adapter leaked into non-full-Gecko build')
    (BUILD / 'test-report.json').write_text(json.dumps({
        'passed': True, 'cycles': 32, 'asan_ubsan': True,
        'actual_adapter_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'host_module_symbol_and_firmware_doubles': True,
        'sdk_clock_names_renamed_in_host_test_only': True,
        'threaded_once_binding_exercised': True,
        'non_full_gecko_adapter_object_has_no_defined_symbols': True,
        'firmware_clock_accuracy_verified': False, 'firmware_condition_deadlines_verified': False,
        'gecko_rendering_or_freeze_repair_verified': False
    }, indent=2) + '\n')
    print('Actual clock adapter: coherent enum mapping / real error propagation / output guards / null resolution / pthread error conventions / concurrent once-binding, 32 ASan/UBSan cycles PASS (firmware doubles)')
if __name__ == '__main__': main()
