#!/usr/bin/env python3
"""Test actual Orbis-gated SpiderMonkey converters and SDK wchar ABI under ASan/UBSan.
Uses the existing same-pin host engine; does not modify its archive or SDK archives.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'build/gecko-host'
OUT = ROOT / 'build/orbis-character-encoding-host'
SDK = ROOT / '.deps/OpenOrbis/PS4Toolchain'
SOURCE = ROOT / '.deps/gecko-layout/js/src/vm/CharacterEncoding.cpp'

def run(args, log, cwd=ROOT):
    with (OUT / log).open('w') as output:
        subprocess.run(list(map(str, args)), cwd=cwd, stdout=output, stderr=subprocess.STDOUT, check=True)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / 'test-report.json'
    report.unlink(missing_ok=True)
    if 'CopyOrbisNativeUtf8' not in SOURCE.read_text():
        raise RuntimeError('Prepare the patched full-Gecko source first')
    rust = list(HOST.glob('*/release/libjsrust.a'))
    if len(rust) != 1 or not (HOST / 'liborbisfox-gecko-support.a').exists():
        raise RuntimeError('Run scripts/test-javascript.py to prepare the matching host engine first')
    flags = ['clang++', '-std=c++20', '-O1', '-g', '-fno-rtti', '-fno-exceptions',
             '-fno-sized-deallocation', '-fno-aligned-new', '-fsanitize=address,undefined',
             '-fno-omit-frame-pointer', '-I' + str(HOST / 'dist/include'),
             '-include', HOST / 'js/src/js-confdefs.h']
    run(flags + ['-D__ORBIS__', '-DMOZILLA_INTERNAL_API',
                 '-I' + str(ROOT / '.deps/gecko-layout/js/src'),
                 '-I' + str(HOST / 'js/src'), '-c', SOURCE, '-o', OUT / 'CharacterEncoding.o'], 'compile.log')
    run(['llvm-ar', 'x', SDK / 'lib/libc.a', 'wcslen.lo'], 'sdk-extract.log', cwd=OUT)
    run(['llvm-objcopy', '--redefine-sym', 'wcslen=orbis_sdk_wcslen',
         OUT / 'wcslen.lo', OUT / 'sdk-wcslen.o'], 'sdk-alias.log')
    run(['llvm-objcopy', '--redefine-sym',
         '_ZN2JS18EncodeNarrowToUtf8EP9JSContextPKc=orbis_test_native_to_utf8',
         '--redefine-sym', '_ZN2JS18EncodeUtf8ToNarrowEP9JSContextPKc=orbis_test_utf8_to_native',
         OUT / 'CharacterEncoding.o', OUT / 'renamed.o'], 'converter-alias.log')
    # Host archive uses unified objects: isolate only these two real converter
    # functions instead of permitting duplicate definitions at the linker.
    # Keep ASan section-boundary globals untouched.
    symbols = []
    for line in subprocess.check_output(['llvm-nm', '--defined-only', '--extern-only', OUT / 'renamed.o'], text=True).splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in ('T', 'W') and not parts[2].startswith('orbis_test_'):
            symbols.append(parts[2])
    (OUT / 'localize.txt').write_text('\n'.join(symbols) + '\n')
    run(['llvm-objcopy', '--localize-symbols=' + str(OUT / 'localize.txt'),
         OUT / 'renamed.o', OUT / 'isolated.o'], 'converter-isolate.log')
    run(flags + [ROOT / 'tests/orbis_character_encoding_test.cpp', OUT / 'isolated.o',
                 OUT / 'sdk-wcslen.o', HOST / 'js/src/build/libjs_static.a',
                 HOST / 'liborbisfox-gecko-support.a', rust[0], '-lpthread', '-ldl', '-lm',
                 '-o', OUT / 'test'], 'link.log')
    run([OUT / 'test'], 'test.log')
    report.write_text(json.dumps({'passed': True, 'cycles': 32,
        'actual_patched_spidermonkey_converters_sanitized': True,
        'host_engine_archive_sanitized': False, 'actual_sdk_wcslen_object_used': True,
        'sdk_cpp_wchar_width_mismatch_reproduced': True,
        'ascii_empty_bmp_non_bmp_roundtrip_passed': True,
        'malformed_utf8_rejection_and_exception_recovery_passed': True,
        'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'firmware_execution_verified': False}, indent=2) + '\n')
    print((OUT / 'test.log').read_text().strip())

if __name__ == '__main__':
    main()
