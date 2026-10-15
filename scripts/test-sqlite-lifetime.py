#!/usr/bin/env python3
"""Actual Gecko SQLite lifetime plus actual pinned SQLite on a host filesystem."""
import hashlib
import json
from pathlib import Path
import resource
import shutil
import signal
import subprocess
ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / 'build/sqlite-lifetime-host'
SOURCE = ROOT / '.deps/gecko-layout'

def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    for name in ('AutoSQLiteLifetime.cpp', 'AutoSQLiteLifetime.h'):
        shutil.copyfile(SOURCE / 'toolkit/xre' / name, BUILD / name)
    # MOZ_MEMORY is disabled, exactly as in the Orbis configuration. No Gecko
    # diagnostic framework is linked: only its abort/warning boundaries doubled.
    (BUILD / 'nsDebug.h').write_text('''#pragma once
#include <cstdlib>
#include <cstdio>
#define MOZ_CRASH(message) do { fputs(message, stderr); std::abort(); } while (0)
#define NS_WARNING_ASSERTION(condition,message) do { if (!(condition)) fputs(message,stderr); } while (0)
''')
    (BUILD / 'mozilla').mkdir(exist_ok=True)
    (BUILD / 'mozilla/Atomics.h').write_text('#pragma once\n// Unused with MOZ_MEMORY disabled.\n')
    sqlite = SOURCE / 'third_party/sqlite3/src'
    binary = BUILD / 'sqlite-lifetime-test'
    flags = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread']
    with (BUILD / 'compile.log').open('w') as log:
        subprocess.run(['clang', *flags, '-c', str(sqlite / 'sqlite3.c'), '-o', str(BUILD / 'sqlite3.o')],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['clang++', '-std=c++20', *flags, '-I' + str(BUILD), '-I' + str(sqlite), '-I' + str(ROOT / 'include'),
                        str(BUILD / 'AutoSQLiteLifetime.cpp'), str(ROOT / 'gecko/orbisfox/native/sqlite_vfs.cpp'), str(ROOT / 'tests/sqlite_lifetime_test.cpp'),
                        str(BUILD / 'sqlite3.o'), '-ldl', '-Wl,--wrap=sqlite3_initialize', '-o', str(binary)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    for cycle in range(32):
        subprocess.run([str(binary), 'success'], check=True, timeout=10)
        subprocess.run([str(binary), 'init-failure'], check=True, timeout=10)
        result = subprocess.run([str(binary), 'duplicate-owner'], stderr=subprocess.PIPE, timeout=10)
        if result.returncode != -signal.SIGABRT: raise ValueError('Singleton lifetime check not enforced')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    (BUILD / 'test-report.json').write_text(json.dumps({
        'passed': True, 'cycles_each_success_and_injected_init_failure_and_duplicate_owner': 32,
        'asan_ubsan': True, 'actual_gecko_lifetime_source_sha256': sha(BUILD / 'AutoSQLiteLifetime.cpp'),
        'actual_pinned_sqlite_source_sha256': sha(sqlite / 'sqlite3.c'),
        'genuine_sqlite_host_persistent_commit_reopen_utf8_rollback_verified': True,
        'actual_vfs_installer_get_set_readback_and_duplicate_rejection_verified': True,
        'vfs_host_linux_passthrough_adapter_double': True,
        'gecko_diagnostics_boundary_doubles': True, 'sqlite_init_failure_injected_only_in_host_test': True,
        'firmware_abi_or_storage_verified': False, 'xpcom_or_cookie_service_verified': False,
        'networking_or_crash_repair_hardware_verified': False
    }, indent=2) + '\n')
    print('Actual Gecko AutoSQLiteLifetime + pinned SQLite: MISUSE before owner, initialize/commit/reopen/UTF-8/rollback/shutdown, init error propagation and singleton rejection, 32 ASan/UBSan cycles each PASS (host filesystem, diagnostic boundaries and injected init failure)')
if __name__ == '__main__': main()
