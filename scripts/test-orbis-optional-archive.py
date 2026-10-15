#!/usr/bin/env python3
"""Sanitize the actual font archive scanner using host archive/cache doubles.
This tests optional-reader/error policy, not real ZIP parsing or rendering.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/orbis-optional-archive-host'
def main():
    spec=importlib.util.spec_from_file_location('optional_gfx',ROOT/'scripts/test-optional-gfx.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    OUT.mkdir(parents=True,exist_ok=True)
    report=OUT/'test-report.json';report.unlink(missing_ok=True)
    source=(ROOT/'.deps/gecko-layout/gfx/thebes/gfxFT2FontList.cpp').read_text()
    body=module.function(source,'void gfxFT2FontList::FindFontsInOmnijar(')
    (OUT/'optional-archive-function.inc').write_text(body+'\n')
    cmd=['clang++','-std=c++20','-O1','-g','-DMOZ_WIDGET_ORBIS','-fsanitize=address,undefined',
         '-fno-omit-frame-pointer','-I'+str(OUT),str(ROOT/'tests/orbis_optional_archive_test.cpp'),'-o',str(OUT/'test')]
    with (OUT/'compile.log').open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (OUT/'test.log').open('w') as log:
        subprocess.run([str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,check=True)
    report.write_text(json.dumps({'passed':True,'cycles':32,'actual_scanner_body_sanitized':True,
        'host_archive_cache_and_type_doubles':True,'actual_zip_implementation_tested':False,
        'source_sha256':hashlib.sha256(body.encode()).hexdigest(),
        'firmware_verified':False,'font_rendering_verified':False},indent=2)+'\n')
    print((OUT/'test.log').read_text().strip())
if __name__=='__main__':main()
