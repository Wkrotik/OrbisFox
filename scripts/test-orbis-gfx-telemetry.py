#!/usr/bin/env python3
"""Sanitize actual telemetry/error-log bodies with host service/metric doubles.
No real GPU identity or hardware telemetry claim is made by these tests.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/orbis-gfx-telemetry-host'
def main():
    spec=importlib.util.spec_from_file_location('optional_gfx',ROOT/'scripts/test-optional-gfx.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    OUT.mkdir(parents=True,exist_ok=True)
    report=OUT/'test-report.json';report.unlink(missing_ok=True)
    source=(ROOT/'.deps/gecko-layout/gfx/thebes/gfxPlatform.cpp').read_text()
    logging=(ROOT/'.deps/gecko-layout/gfx/thebes/gfxFailure.h').read_text()
    body=module.function(source,'void gfxPlatform::ReportTelemetry()')+'\n'
    body+=module.function(logging,'inline void LogFailure(')+'\n'
    (OUT/'gfx-telemetry-functions.inc').write_text(body)
    cmd=['clang++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',
         '-I'+str(OUT),str(ROOT/'tests/orbis_gfx_telemetry_test.cpp'),'-o',str(OUT/'test')]
    with (OUT/'compile.log').open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (OUT/'test.log').open('w') as log:
        subprocess.run([str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,check=True)
    report.write_text(json.dumps({'passed':True,'cycles':32,'actual_function_bodies_sanitized':True,
        'host_screen_metric_and_service_doubles':True,'source_sha256':hashlib.sha256(body.encode()).hexdigest(),
        'firmware_verified':False,'actual_gpu_metadata_verified':False},indent=2)+'\n')
    print((OUT/'test.log').read_text().strip())
if __name__=='__main__':main()
