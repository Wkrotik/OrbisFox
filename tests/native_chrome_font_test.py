"""Real packaged Noto -> public stb atlas -> independent chrome pixel renderer.
ASan/UBSan host raster proof only; no firmware timing or presentation claim.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class NativeChromeFontTest(unittest.TestCase):
 def test_real_noto_bake_and_worker_render(self):
  fonts=list((ROOT/'build/gecko-layout/offline-assets/fonts').glob('NotoSans-Regular.ttf'))
  self.assertTrue(fonts,'Pinned packaged Noto font required')
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)
   (path/'test.cpp').write_text('''#include "orbisfox/native_chrome.h"
#include <cassert>
#include <vector>
int main(int argc,char** argv){assert(argc==2);assert(!orbisfox::prepare_native_chrome_font("/no/such/font"));assert(orbisfox::prepare_native_chrome_font(argv[1]));
 orbisfox::ChromeScene scene{};assert(orbisfox::parse_chrome_scene("2|0|1|content|content|||110|",scene));orbisfox::NativeChrome chrome;chrome.update(scene);chrome.input(8,0,0);chrome.input(0,0,0);
 std::vector<unsigned char> pixels(1280*720*4);orbisfox::Surface s{pixels.data(),1280,720,1280*4};chrome.render(s);
 unsigned antialiased=0;for(int y=155;y<178;++y)for(int x=918;x<1090;++x){auto* p=s.pixels+y*s.stride+x*4;if(p[0]>43&&p[0]<251)++antialiased;}assert(antialiased>20);
}
''')
   command=['clang++','-std=c++20','-O1','-g','-fsanitize=address,undefined','-DORBISFOX_FULL_GECKO','-I'+str(ROOT/'include'),'-idirafter',str(ROOT/'.deps/OpenOrbis/PS4Toolchain/include'),str(path/'test.cpp'),str(ROOT/'src/native_chrome.cpp'),str(ROOT/'src/surface.cpp'),'-pthread','-o',str(path/'test')]
   result=subprocess.run(command,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   result=subprocess.run([str(path/'test'),str(fonts[0])],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
