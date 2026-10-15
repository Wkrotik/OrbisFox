#!/usr/bin/env python3
"""Actual native diagnostic monitor body, sanitized with host file/sleep doubles."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/gecko-heartbeat-host'
def main():
    spec=importlib.util.spec_from_file_location('optional_gfx',ROOT/'scripts/test-optional-gfx.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    OUT.mkdir(parents=True,exist_ok=True)
    report=OUT/'test-report.json';report.unlink(missing_ok=True)
    body=helper.function((ROOT/'gecko/orbisfox/native/main.cpp').read_text(),'void* monitor(void* opaque)')
    for forbidden in ('controller.poll','request_system_exit','mWidget','XRE_','JS::'):
        assert forbidden not in body
    (OUT/'monitor-function.inc').write_text(body+'\n')
    cmd=['clang++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
         '-I'+str(OUT),str(ROOT/'tests/gecko_heartbeat_test.cpp'),'-o',str(OUT/'test')]
    with (OUT/'compile.log').open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True,cwd=ROOT)
    with (OUT/'test.log').open('w') as log:subprocess.run([str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,check=True,cwd=ROOT)
    report.write_text(json.dumps({'passed':True,'cycles':32,'actual_monitor_body_sanitized':True,
        'host_file_sleep_and_atomic_state_doubles':True,'source_sha256':hashlib.sha256(body.encode()).hexdigest(),
        'firmware_threading_verified':False,'freeze_fixed':False,'fixture_assertions_verified':False},indent=2)+'\n')
    print((OUT/'test.log').read_text().strip())
if __name__=='__main__':main()
