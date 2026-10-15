#!/usr/bin/env python3
"""Actual Net-module readiness with explicit module/firmware doubles."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
BUILD=ROOT/'build/native-network-host'
def main():
    BUILD.mkdir(parents=True,exist_ok=True)
    (BUILD/'orbis').mkdir(exist_ok=True)
    (BUILD/'orbis/Sysmodule.h').write_text('#pragma once\n#define ORBIS_SYSMODULE_INTERNAL_NET 0x8000001C\n')
    source=ROOT/'src/ps4/native_network.cpp';binary=BUILD/'native-network-test'
    with (BUILD/'compile.log').open('w') as log:
        subprocess.run(['clang++','-std=c++20','-DORBISFOX_FULL_GECKO','-O1','-g',
            '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(BUILD),'-I'+str(ROOT/'include'),
            str(source),str(ROOT/'tests/native_network_test.cpp'),'-o',str(binary)],stdout=log,stderr=subprocess.STDOUT,check=True)
    subprocess.run([str(binary)],check=True,timeout=30)
    inactive=BUILD/'non-full-gecko-empty.o'
    subprocess.run(['clang++','-c',str(source),'-o',str(inactive)],check=True)
    assert not subprocess.check_output(['llvm-nm','-g','--defined-only',str(inactive)],text=True).strip()
    (BUILD/'test-report.json').write_text(json.dumps({'passed':True,'cycles':32,'asan_ubsan':True,
        'actual_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'host_module_firmware_doubles':True,
        'failures_never_call_unbound_import_or_guess_dns_abi':True,'init_error_codes_not_forged_as_success':True,
        'non_full_gecko_empty_object_verified':True,'firmware_import_patching_or_dns_http_tls_verified':False},indent=2)+'\n')
    print('Actual Net module readiness: load/init/resolver symbols, failure gates, no unknown init-code acceptance, stable lane isolation, 32 ASan/UBSan cycles PASS (module/firmware doubles)')
if __name__=='__main__':main()
