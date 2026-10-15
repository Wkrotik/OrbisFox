#!/usr/bin/env python3
"""Actual native bridge method with explicit Gecko/XPConnect ownership doubles."""
from pathlib import Path
import subprocess,json
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/window-provider-host';OUT.mkdir(exist_ok=True)
source=(ROOT/'gecko/orbisfox/window-provider.inc').read_text()
method=source[source.index('NS_IMETHODIMP WebBrowserChrome2Stub::ProvideWindow('):]
harness=(ROOT/'tests/window_provider_test.cpp').read_text().replace('// ACTUAL_PROVIDER_METHOD',method)
(OUT/'extracted-test.cpp').write_text(harness)
with (OUT/'compile.log').open('w') as log:
 subprocess.run(['clang++','-std=c++20','-O1','-g','-Wall','-Wextra','-Werror',
  '-Wno-unused-parameter','-fsanitize=address,undefined','-fno-omit-frame-pointer',
  str(OUT/'extracted-test.cpp'),'-o',str(OUT/'test')],check=True,stdout=log,stderr=subprocess.STDOUT)
with (OUT/'test.log').open('w') as log:subprocess.run([str(OUT/'test')],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=30)
(OUT/'test-report.json').write_text(json.dumps({'passed':True,'cycles':32,'actual_method_extracted':True,
 'explicit_Gecko_XPConnect_ownership_doubles':True,'full_windowwatcher_chain_host_executed':False,
 'firmware_tested':False,'original_heap_crash_fixed_claimed':False},indent=2)+'\n')
print((OUT/'test.log').read_text())
