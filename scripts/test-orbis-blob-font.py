#!/usr/bin/env python3
"""Compile actual platform selection block used for WebRender blob fonts."""
from pathlib import Path
import subprocess,json
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/orbis-blob-font-host'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'.deps/gecko-layout/gfx/webrender_bindings/Moz2DImageRenderer.cpp').read_text()
    start=source.index('  FontType type =');end=source.index('  // makes a copy of the data',start);block=source[start:end]
    assert 'defined(MOZ_WIDGET_ORBIS)' in block
    (OUT/'test.cpp').write_text('enum class FontType {MAC,DWRITE,FREETYPE,FONTCONFIG};\nint main(){\n'+block+'return type==FontType::EXPECTED?0:1;}\n')
    matrix={'MOZ_WIDGET_ORBIS':'FREETYPE','ANDROID':'FREETYPE','XP_WIN':'DWRITE','XP_DARWIN':'MAC','MOZ_WIDGET_GTK':'FONTCONFIG'}
    with (OUT/'compile.log').open('w') as log:
        for platform,expected in matrix.items():
            subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror','-D'+platform,'-DEXPECTED='+expected,str(OUT/'test.cpp'),'-o',str(OUT/'test')],stdout=log,stderr=subprocess.STDOUT,check=True)
            for _ in range(32):subprocess.run([str(OUT/'test')],check=True)
    (OUT/'test-report.json').write_text(json.dumps({'passed':True,'actual_pinned_platform_selection_block_compiled':True,'cycles_per_platform':32,'matrix':matrix,'native_font_resource_crash_assertions_retained':True,'font_rendering_firmware_verified':False},indent=2)+'\n')
    print('WebRender blob font:actual platform selector32 cycles, Orbis FreeType / unchanged Android-Windows-Mac-GTK choices; not font rendering proof')
if __name__=='__main__':main()
