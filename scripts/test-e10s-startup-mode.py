#!/usr/bin/env python3
"""Sanitize actual pinned global E10s startup policy with explicit host doubles."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/e10s-startup-mode-host'
def main():
    spec = importlib.util.spec_from_file_location('optional_gfx', ROOT / 'scripts/test-optional-gfx.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / 'test-report.json'; report.unlink(missing_ok=True)
    text = (ROOT / '.deps/gecko-layout/toolkit/xre/nsAppRunner.cpp').read_text()
    body = helper.function(text, 'bool BrowserTabsRemoteAutostart()')
    assert 'MOZ_FORCE_DISABLE_E10S' in body
    assert 'browser.tabs.remote.autostart' not in body
    (OUT / 'e10s-policy.inc').write_text(body + '\n')
    config = (ROOT / 'build/gecko-layout/dist/include/mozilla-config.h').read_text()
    assert not any(line.startswith('#define MOZILLA_OFFICIAL') for line in config.splitlines()), 'Supported nonofficial switch must remain available in the target engine'
    for official in (False, True):
        name = 'official' if official else 'development'
        executable = OUT / name
        command = ['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                   '-fno-omit-frame-pointer', '-I' + str(OUT)]
        if official: command.append('-DMOZILLA_OFFICIAL')
        command += [str(ROOT / 'tests/e10s_startup_mode_test.cpp'), '-o', str(executable)]
        with (OUT / (name + '-compile.log')).open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        with (OUT / (name + '-test.log')).open('w') as log:
            subprocess.run([str(executable)], stdout=log, stderr=subprocess.STDOUT, check=True)
        print(name + ': ' + (OUT / (name + '-test.log')).read_text().strip())
    report.write_text(json.dumps({'passed': True, 'cycles_each_build': 32,
        'actual_startup_policy_sanitized': True, 'host_process_and_nspr_environment_doubles': True,
        'official_and_nonofficial_matrix': True, 'target_engine_nonofficial_confirmed': True,
        'source_sha256': hashlib.sha256(body.encode()).hexdigest(),
        'firmware_verified': False, 'document_loading_verified': False, 'rendering_verified': False}, indent=2) + '\n')
if __name__ == '__main__': main()
