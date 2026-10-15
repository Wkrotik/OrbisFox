#!/usr/bin/env python3
"""Sanitize actual patched FT2 font-policy bodies with host boundary doubles.
No graphics service is provided: any accidental device-query dependency fails
compilation. This is policy coverage, not glyph rendering or firmware proof.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/orbis-font-visibility-host'

def main():
    spec = importlib.util.spec_from_file_location('optional_gfx', ROOT / 'scripts/test-optional-gfx.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    OUT.mkdir(parents=True, exist_ok=True)
    report=OUT/'test-report.json'; report.unlink(missing_ok=True)
    source=(ROOT/'.deps/gecko-layout/gfx/thebes/gfxFT2FontList.cpp').read_text()
    start=source.index('static const char* kBaseFonts_Orbis[]')
    constant=source[start:source.index(';',start)+1]
    body=constant+'\n'+module.function(source,'FontVisibility gfxFT2FontList::GetVisibilityForFamily(')+'\n'
    # Include the multiline return type before the method signature.
    body+='nsTArray<std::pair<const char**, uint32_t>>\n'+module.function(source,'gfxFT2FontList::GetFilteredPlatformFontLists()')+'\n'
    (OUT/'orbis-font-functions.inc').write_text(body)
    cmd=['clang++','-std=c++20','-O1','-g','-DMOZ_WIDGET_ORBIS','-fsanitize=address,undefined',
         '-fno-omit-frame-pointer','-I'+str(OUT),str(ROOT/'tests/orbis_font_visibility_test.cpp'),'-o',str(OUT/'test')]
    with (OUT/'compile.log').open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (OUT/'test.log').open('w') as log:
        subprocess.run([str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,check=True)
    report.write_text(json.dumps({'passed':True,'cycles':32,'actual_function_bodies_sanitized':True,
        'host_type_and_ascii_comparator_doubles':True,'graphics_service_available_in_test':False,
        'extracted_source_sha256':hashlib.sha256(body.encode()).hexdigest(),
        'glyph_rendering_verified':False,'firmware_verified':False},indent=2)+'\n')
    print((OUT/'test.log').read_text().strip())

if __name__=='__main__': main()
