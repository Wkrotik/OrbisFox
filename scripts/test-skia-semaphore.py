#!/usr/bin/env python3
"""Compile actual pinned Skia synchronization, not a reimplemented mutex model."""
from pathlib import Path
import subprocess
import json
import argparse
args = argparse.ArgumentParser()
args.add_argument('--tsan', action='store_true', help='Also run actual Skia host contention under ThreadSanitizer')
options = args.parse_args()
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/skia-semaphore-host'
SKIA = ROOT / '.deps/gecko-layout/gfx/skia/skia'
OUT.mkdir(parents=True, exist_ok=True)
(OUT/'test-report.json').unlink(missing_ok=True)
APIS = ['pthread_mutex_init', 'pthread_mutex_destroy', 'pthread_mutex_lock',
        'pthread_mutex_unlock', 'pthread_cond_init', 'pthread_cond_destroy',
        'pthread_cond_broadcast', 'pthread_cond_wait']
command = ['clang++', '-std=c++20', '-O1', '-g', '-UNDEBUG', '-DMOZ_WIDGET_ORBIS',
           '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
           '-I'+str(SKIA), '-I'+str(ROOT/'gecko'),
           str(ROOT/'tests/skia_semaphore_test.cpp'), str(SKIA/'src/base/SkSemaphore.cpp'),
           str(SKIA/'src/base/SkThreadID.cpp'),
           *['-Wl,--wrap='+api for api in APIS], '-o', str(OUT/'test')]
with (OUT/'compile.log').open('w') as log:
    subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
with (OUT/'test.log').open('w') as log:
    subprocess.run([str(OUT/'test')], check=True, stdout=log, stderr=subprocess.STDOUT, timeout=60)
# Compile the unmodified pinned source too: injected POSIX wait error must
# demonstrate the old false-acquisition mechanism, not infer console behavior.
original = subprocess.check_output(['git','-C',str(ROOT/'.deps/gecko-layout'),
    'show','HEAD:gfx/skia/skia/src/base/SkSemaphore.cpp'], text=True)
(OUT/'original-SkSemaphore.cpp').write_text(original)
legacy = ['clang++','-std=c++20','-O1','-g','-DNDEBUG','-pthread',
          '-fsanitize=address,undefined','-I'+str(SKIA),
          str(ROOT/'tests/skia_semaphore_legacy_failure_test.cpp'),str(OUT/'original-SkSemaphore.cpp'),
          *['-Wl,--wrap='+api for api in ['sem_init','sem_destroy','sem_post','sem_wait']],
          '-o',str(OUT/'legacy-error-test')]
with (OUT/'legacy-compile.log').open('w') as log:subprocess.run(legacy,check=True,stdout=log,stderr=subprocess.STDOUT)
with (OUT/'legacy-test.log').open('w') as log:subprocess.run([str(OUT/'legacy-error-test')],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=10)
report = {'passed': True, 'actual_pinned_SkSemaphore_SkMutex': True,
          'original_error_false_acquisition_reproduced_with_explicit_double': True,
          'cycles': 32, 'workers': 8, 'acquisitions_per_worker': 256,
          'explicit_spurious_wakes': True, 'fatal_pthread_error_cases': APIS,
          'sanitizers': ['address', 'undefined'], 'firmware_tested': False}
(OUT/'test-report.json').write_text(json.dumps(report, indent=2)+'\n')
print((OUT/'test.log').read_text())
print((OUT/'legacy-test.log').read_text())
if options.tsan:
    (OUT/'tsan-report.json').unlink(missing_ok=True)
    tsan = ['g++','-std=c++20','-O1','-g','-UNDEBUG','-DMOZ_WIDGET_ORBIS',
            '-fsanitize=thread','-fno-omit-frame-pointer','-pthread','-no-pie',
            '-I'+str(SKIA),'-I'+str(ROOT/'gecko'),str(ROOT/'tests/skia_semaphore_test.cpp'),
            str(SKIA/'src/base/SkSemaphore.cpp'),str(SKIA/'src/base/SkThreadID.cpp'),
            *['-Wl,--wrap='+api for api in APIS],'-o',str(OUT/'test-tsan')]
    with (OUT/'tsan-compile.log').open('w') as log:subprocess.run(tsan,check=True,stdout=log,stderr=subprocess.STDOUT)
    with (OUT/'tsan-test.log').open('w') as log:subprocess.run([str(OUT/'test-tsan')],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=60)
    (OUT/'tsan-report.json').write_text(json.dumps({'passed':True,'actual_Skia_pthread_contention':True,
        'cycles':32,'workers':8,'sanitizer':'thread','firmware_tested':False},indent=2)+'\n')
    print('Actual Skia host pthread contention ThreadSanitizer PASS; no firmware proof')
