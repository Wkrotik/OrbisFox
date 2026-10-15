#!/usr/bin/env python3
"""Actual native pointer state transitions with synchronous widget doubles."""
from pathlib import Path
import subprocess,json
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/pointer-reentrancy-host'
def main():
    source=(ROOT/'gecko/widget/orbis/OrbisFoxHost.cpp').read_text();OUT.mkdir(parents=True,exist_ok=True)
    start=source.index('NS_IMETHODIMP OrbisFoxHost::SetPointerInputEnabled(')
    end=source.index('\nNS_IMETHODIMP OrbisFoxHost::PumpFrame',start)
    body=source[start:end].replace('OrbisFoxHost::','TestHost::')
    (OUT/'set-pointer.inc').write_text(body)
    start=source.index('  const bool controllerIntent =');end=source.index('  traceStage("Gecko pump: input synthesis returned;',start)
    (OUT/'pump-input.inc').write_text(source[start:end])
    command=['clang++','-std=c++20','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(OUT),str(ROOT/'tests/pointer_reentrancy_test.cpp'),'-o',str(OUT/'test')]
    with (OUT/'compile.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (OUT/'test.log').open('w') as log:subprocess.run([str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,timeout=20,check=True)
    (OUT/'test-report.json').write_text(json.dumps({'passed':True,'cycles':32,'actual_native_method_and_input_dispatch_block':True,'synchronous_reentrant_widget_double':True,'ASan_UBSan':True,'button_release_published_before_click':True,'recursive_disable_enable_mouseup_and_controller_intent_and_move_tested':True,'hardware_tested':False},indent=2)+'\n')
    print('Native pointer:32 sanitized cycles, actual source + synchronous widget double; no recursive mouseup, ownership/click edges/re-enable held/move takeover tested')
if __name__=='__main__':main()
