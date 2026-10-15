#!/usr/bin/env python3
"""Sanitize pinned frame-loader policy and boolean-attribute accessor; DOM doubles."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/initial-frame-remoteness-host'
def main():
    spec = importlib.util.spec_from_file_location('extract', ROOT / 'scripts/test-optional-gfx.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    OUT.mkdir(parents=True, exist_ok=True)
    policy = helper.function((ROOT / '.deps/gecko-layout/dom/base/nsFrameLoader.cpp').read_text(), 'static bool InitialLoadIsRemote(')
    accessor = helper.function((ROOT / '.deps/gecko-layout/dom/base/Element.h').read_text(), 'bool GetBoolAttr(')
    (OUT / 'policy.inc').write_text(policy + '\n')
    (OUT / 'accessor.inc').write_text(accessor + '\n')
    command = ['clang++', '-std=c++20', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I'+str(OUT),
               str(ROOT / 'tests/initial_frame_remoteness_test.cpp'), '-o', str(OUT / 'test')]
    with (OUT / 'compile.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    subprocess.run([str(OUT / 'test')], check=True)
    (OUT / 'test-report.json').write_text(json.dumps({'passed':True,'cycles':32,
        'actual_pinned_policy_and_boolean_accessor':True,'asan_ubsan':True,
        'explicit_dom_process_and_attribute_doubles':True,'firmware_and_frameloader_not_certified':True,
        'policy_sha256':hashlib.sha256(policy.encode()).hexdigest(),
        'accessor_sha256':hashlib.sha256(accessor.encode()).hexdigest()},indent=2)+'\n')
    print('Initial frame remoteness:32 cycles pinned policy/accessor; DOM/process doubles, no firmware proof')
if __name__ == '__main__': main()
