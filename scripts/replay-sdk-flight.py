#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline retained-size replay; synthetic payloads and Linux shims, not firmware proof."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import runpy
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/sdk-flight-replay'

def sha(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()

def no_core():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    args = parser.parse_args()
    trace = args.trace.resolve(strict=True)
    commands = ROOT / 'build/mesa-sdk-allocator-host/commands.json'
    if not commands.exists():
        subprocess.run(['/usr/bin/python3', ROOT / 'scripts/test-mesa-sdk-allocator.py'], check=True)
    sdk = runpy.run_path(str(ROOT / 'scripts/test-sdk-allocator.py'))
    prepared = json.loads((sdk['OUT'] / 'test-report.json').read_text())
    for member in sdk['MEMBERS']:
        original = subprocess.check_output(['llvm-ar', 'p', sdk['ARCHIVE'], member])
        if hashlib.sha256(original).hexdigest() != prepared['object_hashes'][member]:
            raise RuntimeError('SDK source object changed: ' + member)
    OUT.mkdir(parents=True, exist_ok=True)
    # Reuse the exact genuine-object link recipe; no browser tree build or SDK edit.
    command = json.loads(commands.read_text())[1]
    command = [str(ROOT / 'tests/sdk_flight_replay_test.cpp') if x == str(ROOT / 'tests/mesa_sdk_allocator_test.cpp') else x for x in command]
    command[command.index('-o') + 1] = str(OUT / 'replay')
    with (OUT / 'compile.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    report = {'trace_sha256': sha(trace), 'harness_sha256': sha(ROOT / 'tests/sdk_flight_replay_test.cpp'),
              'native_wrapper_sha256': sha(ROOT / 'src/ps4/native_allocator.cpp'),
              'sdk_object_sha256': prepared['object_hashes'], 'compile': command,
              'cases': [], 'passed': False, 'firmware_tested': False,
              'limitations': ['Retained window only; earlier allocations and unknown realloc inputs cannot be replayed exactly.',
                              'Synthetic data, remapped addresses and serialized API order, not original browser writes or timing.',
                              'Allocator/VM OS shims run on Linux; real SDK objects are not sanitizer-instrumented.',
                              'Failed recorded allocations are skipped; no fault injection reproduces native pool pressure.']}
    report_path = OUT / (trace.parent.name + '-report.json')
    for direct in (False, True):
        env = {k: v for k, v in os.environ.items() if not k.startswith('SDK_TEST_')}
        env['SDK_TEST_MREMAP_ENOSYS'] = '1'
        if direct:
            env['SDK_TEST_DIRECT_BACKING'] = '1'
        log_path = OUT / (trace.parent.name + '-direct-' + str(int(direct)) + '.log')
        start = time.monotonic()
        with log_path.open('w') as log:
            result = subprocess.run([str(OUT / 'replay'), str(trace)], env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=300, preexec_fn=no_core)
        report['cases'].append({'direct_memory_double': direct, 'mremap_ENOSYS': True,
                                'returncode': result.returncode, 'seconds': time.monotonic()-start,
                                'log': str(log_path)})
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(log_path.read_text()[-3000:], flush=True)
        if result.returncode:
            raise SystemExit('Retained SDK replay failed; see ' + str(report_path))
    report['passed'] = True
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print('Report:', report_path)

if __name__ == '__main__':
    main()
