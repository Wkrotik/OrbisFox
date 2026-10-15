#!/usr/bin/env python3
"""Actual optional-GfxInfo function-body tests with host XPCOM boundary doubles.
Not a full-engine or firmware certification. Also tests the actual JS directory
provider's no-file fallback against DirectoryService's documented contract.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/optional-gfx-host'

def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1; pos = brace + 1
    while depth:
        depth += (text[pos] == '{') - (text[pos] == '}')
        pos += 1
    return text[start:pos]

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = OUT / 'test-report.json'; report.unlink(missing_ok=True)
    header = (ROOT / 'gecko/widget/orbis/OrbisGfxInfo.h').read_text()
    platform = (ROOT / '.deps/gecko-layout/gfx/thebes/gfxPlatform.cpp').read_text()
    helper = function(header, 'inline nsresult GetOptionalGfxFeatureStatus(')
    caller = function(platform, 'static bool IsFeatureSupported(')
    (OUT / 'optional-gfx-functions.inc').write_text(helper + '\n' + caller + '\n')
    command = ['clang++', '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
               '-fno-omit-frame-pointer', '-I' + str(OUT),
               ROOT / 'tests/gfx_optional_feature_test.cpp', '-o', OUT / 'test']
    with (OUT / 'compile.log').open('w') as log:
        subprocess.run(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT, check=True)
    with (OUT / 'test.log').open('w') as log:
        subprocess.run([str(OUT / 'test')], stdout=log, stderr=subprocess.STDOUT, check=True)
    launcher = (ROOT / 'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
    provider = function(launcher, 'const provider = ')
    js = ('"use strict"; const assert = require("node:assert/strict");\n'
          'const profile = {clone: () => ({path:"/data/orbisfox/gecko-profile"})};\n'
          'const ChromeUtils = {generateQI: () => function(){return this}};\n' + provider + ';\n'
          'for(let cycle=0;cycle<32;cycle++){\n'
          ' for(const key of ["ProfD","ProfLD","cachePDir","ProfDS","ProfLDS"]){\n'
          '  const persistent={value:false};const file=provider.getFile(key,persistent);\n'
          '  assert.equal(file.path,"/data/orbisfox/gecko-profile");assert.equal(persistent.value,true);}\n'
          ' for(const key of ["", "GreD", "CurProcD", "UnknownDirectory"]){\n'
          '  const persistent={value:true};assert.equal(provider.getFile(key,persistent),null);\n'
          '  assert.equal(persistent.value,false);}\n'
          '} console.log("Actual JS directory provider: known profile / unrelated-key no-file fallback, 32 cycles PASS");\n')
    (OUT / 'directory-provider-test.js').write_text(js)
    with (OUT / 'directory-test.log').open('w') as log:
        subprocess.run(['node', str(OUT / 'directory-provider-test.js')], stdout=log, stderr=subprocess.STDOUT, check=True)
    report.write_text(json.dumps({'passed':True, 'cycles':32,
        'actual_function_bodies_sanitized':True, 'host_xpcom_boundary_doubles':True,
        'actual_js_directory_provider_exercised':True,
        'helper_caller_sha256':hashlib.sha256((helper+caller).encode()).hexdigest(),
        'full_engine_host_test':False, 'firmware_verified':False},indent=2)+'\n')
    print((OUT / 'test.log').read_text().strip())
    print((OUT / 'directory-test.log').read_text().strip())

if __name__ == '__main__': main()
