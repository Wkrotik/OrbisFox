#!/usr/bin/env python3
"""Actual pinned process-switch eligibility function, host field/DOM doubles."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/standalone-process-switch-host'
def main():
    spec = importlib.util.spec_from_file_location('optional_gfx', ROOT / 'scripts/test-optional-gfx.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / 'test-report.json'; report.unlink(missing_ok=True)
    text = (ROOT / '.deps/gecko-layout/netwerk/ipc/DocumentLoadListener.cpp').read_text()
    body = helper.function(text, 'static bool ContextCanProcessSwitch(')
    (OUT / 'process-switch-policy.inc').write_text(body + '\n')
    command = ['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
               '-fno-omit-frame-pointer', '-I' + str(OUT),
               str(ROOT / 'tests/standalone_process_switch_test.cpp'), '-o', str(OUT / 'test')]
    with (OUT / 'compile.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (OUT / 'test.log').open('w') as log:
        subprocess.run([str(OUT / 'test')], stdout=log, stderr=subprocess.STDOUT, check=True)
    report.write_text(json.dumps({'passed': True, 'cycles': 32,
        'actual_process_switch_eligibility_function_sanitized': True,
        'host_context_dom_and_logging_doubles': True,
        'source_sha256': hashlib.sha256(body.encode()).hexdigest(),
        'full_document_handoff_verified': False, 'firmware_verified': False,
        'rendering_verified': False}, indent=2) + '\n')
    print((OUT / 'test.log').read_text().strip())
if __name__ == '__main__': main()
