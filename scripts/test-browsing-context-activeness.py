#!/usr/bin/env python3
"""Actual pinned activeness-getter policy, sanitized with host field doubles.
Not a native setter/IPC test or rendering certification.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/browsing-context-activeness-host'
def main():
    spec=importlib.util.spec_from_file_location('optional_gfx',ROOT/'scripts/test-optional-gfx.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    OUT.mkdir(parents=True,exist_ok=True)
    report=OUT/'test-report.json';report.unlink(missing_ok=True)
    source=(ROOT/'.deps/gecko-layout/docshell/base/BrowsingContext.cpp').read_text()
    body=module.function(source,'bool BrowsingContext::IsActive() const')
    (OUT/'activeness-function.inc').write_text(body+'\n')
    cmd=['clang++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
         '-I'+str(OUT),str(ROOT/'tests/browsing_context_activeness_test.cpp'),'-o',str(OUT/'test')]
    with (OUT/'compile.log').open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (OUT/'test.log').open('w') as log:
        subprocess.run([str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,check=True)
    report.write_text(json.dumps({'passed':True,'cycles':32,'actual_getter_body_sanitized':True,
        'host_context_field_doubles':True,'source_sha256':hashlib.sha256(body.encode()).hexdigest(),
        'native_setter_ipc_verified':False,'firmware_verified':False,'rendering_verified':False},indent=2)+'\n')
    print((OUT/'test.log').read_text().strip())
if __name__=='__main__':main()
