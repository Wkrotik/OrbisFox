#!/usr/bin/env python3
"""Compile actual patched glyph lookup and buffer checks with explicit data doubles.
Not a complete Skia renderer, font backend, Gecko or firmware test.
"""
from pathlib import Path
import subprocess
import json
ROOT = Path(__file__).resolve().parents[1]
SKIA = ROOT/'.deps/gecko-layout/gfx/skia/skia'
OUT = ROOT/'build/skia-glyph-host'
OUT.mkdir(parents=True, exist_ok=True)
(OUT/'test-report.json').unlink(missing_ok=True)
def function(text, signature):
    start=text.index(signature); brace=text.index('{',start);depth=1;end=brace+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]
lookup=function((SKIA/'src/core/SkStrike.cpp').read_text(),'SkGlyph* SkStrike::glyph(SkGlyphDigest digest)')
producer=function((SKIA/'src/core/SkGlyphRunPainter.cpp').read_text(),'prepare_for_direct_mask_drawing(SkStrike* strike,')
producer=producer[producer.index('{')+1:producer.index('    const SkIPoint mask')]
consumer=function((SKIA/'src/core/SkDraw_text.cpp').read_text(),'void Draw::paintMasks(')
consumer=consumer[consumer.index('{')+1:consumer.index('    SkSTArenaAlloc')]
source=(ROOT/'tests/skia_glyph_invariants_test.cpp').read_text()
source=source.replace('/* ACTUAL_LOOKUP */',lookup).replace('/* ACTUAL_PREPARE */',producer).replace('/* ACTUAL_CONSUME */',consumer)
(OUT/'extracted-test.cpp').write_text(source)
command=['clang++','-std=c++20','-O1','-g','-UNDEBUG','-DMOZ_WIDGET_ORBIS',
         '-fsanitize=address,undefined','-fno-omit-frame-pointer','-pthread',
         '-I'+str(SKIA),'-I'+str(ROOT/'gecko'),str(OUT/'extracted-test.cpp'),
         str(SKIA/'src/base/SkSemaphore.cpp'),str(SKIA/'src/base/SkThreadID.cpp'),'-o',str(OUT/'test')]
with (OUT/'compile.log').open('w') as log:subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT)
with (OUT/'test.log').open('w') as log:subprocess.run([str(OUT/'test')],check=True,stdout=log,stderr=subprocess.STDOUT,timeout=60)
(OUT/'test-report.json').write_text(json.dumps({'passed':True,'actual_extracted_lookup_capacity_consumer_checks':True,
  'actual_pinned_SkMutex':True,'explicit_doubles':['digest','glyph data','strike vector','buffer'],
  'cycles':32,'workers':8,'fatal_invariant_cases':5,'full_font_renderer_tested':False,'firmware_tested':False},indent=2)+'\n')
print((OUT/'test.log').read_text())
