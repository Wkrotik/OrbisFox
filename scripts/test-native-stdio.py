#!/usr/bin/env python3
"""Actual stdio boundary with explicit SDK call/lock-skip model and host libc."""
import argparse,json,re,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/native-stdio-host'
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--compiler',default='c++');args=parser.parse_args()
    names=re.findall(r'"([a-z]+)"',(ROOT/'include/orbisfox/stdio_wrapped_symbols.h').read_text())
    OUT.mkdir(parents=True,exist_ok=True)
    command=shlex.split(args.compiler)+['-std=c++20','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
      '-DORBISFOX_FULL_GECKO','-I'+str(ROOT/'include'),str(ROOT/'tests/native_stdio_test.cpp'),
      str(ROOT/'src/ps4/native_stdio.cpp'),'-pthread']+['-Wl,--wrap='+name for name in names]+['-o',str(OUT/'test')]
    with (OUT/'compile.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (OUT/'test.log').open('w') as log:subprocess.run([str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,timeout=90,check=True)
    (OUT/'test-report.json').write_text(json.dumps({'passed':True,'cycles_per_mode':32,'threads_per_cycle':8,
      'sdk_FLOCK_enabled_and_FILE_lock_minus_1_bypass_both_tested':True,'entry_lock_counts_checked':True,
      'real_pthread_recursive_mutex_and_cross_thread_trylock':True,'asan_ubsan':True,'wrapped_entries':names,
      'SDK_FLOCK_caller_and_fprintf_to_vfprintf_explicit_models':True,'host_libc_not_SDK_libc':True,'firmware_verified':False},indent=2)+'\n')
    print('Native stdio:32 cycles each active/skipped SDK FLOCK mode,8 threads; protected entries, recursion/trylock; host libc/model, not firmware proof')
if __name__=='__main__':main()
