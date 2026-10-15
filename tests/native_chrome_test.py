import pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class NativeChromeTest(unittest.TestCase):
 def test_worker_menu_controls_and_bounded_commands(self):
  source=r'''
#include "orbisfox/native_chrome.h"
#include <cassert>
#include <cstring>
#include <vector>
using namespace orbisfox;
int main(){
 ChromeScene scene{},other{};
 const char* wire="1|0|1|content|content|content-1||6,1200,50,40,38,1;10,100,5,160,36,1;11,300,5,160,36,1;1,10,50,40,38,0;";
 assert(parse_chrome_scene(wire,scene));assert(scene.count==4&&scene.web);
 assert(parse_chrome_scene("2|0|1|content|content|||110|1,0,45,50,30,1;",other)&&other.zoom==110);
 assert(!parse_chrome_scene("2|0|1|content|content|||111|",other));
 for(const char* invalid:{"", "1|0|1|missing|content|||", "1|0|1|content|content|||1,0,0,1281,30,1;", "1|0|1|content|content|||1,0,0,30,105,1;", "1|0|1|content|content|||9,0,0,30,30,1;"})assert(!parse_chrome_scene(invalid,other));
 NativeChrome chrome;chrome.update(scene);char out[48]{};
 // Disabled controls cannot dispatch. Native toolbar press+release is consumed.
 assert(chrome.input(1,20,60)&1);assert(chrome.input(0,20,60)&1);assert(!chrome.take(out,sizeof(out)));
 assert(chrome.input(1,310,10)&1);chrome.input(0,310,10);assert(chrome.take(out,sizeof(out)));assert(!strcmp(out,"11:content-1"));
 assert(chrome.input(1024,800,500)&1024);assert(chrome.input(1024,800,500)&1024);chrome.input(0,800,500);assert(chrome.take(out,sizeof(out)));assert(!chrome.take(out,sizeof(out)));
 // Menu opens, responds, and paints with no Gecko callbacks or new page frame.
 chrome.input(8,950,350);chrome.input(0,950,350);assert(chrome.modal());
 std::vector<uint8_t> pixels(1280*720*4);Surface surface{pixels.data(),1280,720,1280*4};chrome.render(surface);assert(pixels[(110*1280+905)*4]==43);
 chrome.input(1,950,113+8*42+10);chrome.input(0,950,113+8*42+10);assert(chrome.take(out,sizeof(out)));assert(!strcmp(out,"34:"));
 // Zoom left/right keeps menu open; keyboard Cross resets; outside click closes and is swallowed.
 chrome.input(8,950,120);chrome.input(0,950,120);
 for(int i=0;i<6;++i){chrome.input(256,950,120);chrome.input(0,950,120);}
 chrome.input(32,950,120);chrome.input(0,950,120);assert(chrome.take(out,sizeof(out))&&!strcmp(out,"39:"));
 chrome.input(64,950,120);chrome.input(0,950,120);assert(chrome.take(out,sizeof(out))&&!strcmp(out,"40:"));
 chrome.input(1,950,120);chrome.input(0,950,120);assert(chrome.take(out,sizeof(out))&&!strcmp(out,"41:"));
 chrome.input(1,500,500);assert(chrome.input(0,500,500)&1);assert(!chrome.take(out,sizeof(out)));
 chrome.input(8192,310,10);assert(chrome.input(0,310,10)&8192);assert(chrome.take(out,sizeof(out))&&!strcmp(out,"21:content-1"));
 assert(!chrome.modal());
 chrome.input(2048,800,500);chrome.input(0,800,500);assert(chrome.take(out,sizeof(out))&&!strcmp(out,"2:"));
 chrome.input(4096,800,500);chrome.input(0,800,500);assert(chrome.take(out,sizeof(out))&&!strcmp(out,"1:"));
 chrome.input(16384,800,500);chrome.input(0,800,500);assert(chrome.take(out,sizeof(out))&&!strcmp(out,"38:"));
 // Header changes between menu press/release must not cancel New Tab.
 chrome.input(8,950,120);chrome.input(0,950,120);chrome.input(1,950,123);
 ChromeScene changed=scene;changed.controls[1].width=150;chrome.update(changed);
 chrome.input(0,950,123);assert(chrome.take(out,sizeof(out))&&!strcmp(out,"8:"));assert(!chrome.modal());
 chrome.input(16,800,500);chrome.input(0,800,500);assert(chrome.take(out,sizeof(out))&&!strcmp(out,"42:"));
 assert(parse_chrome_scene("2|0|1|content|content|||100|45,400,665,40,40,1;",other));
 assert(!parse_chrome_scene("2|0|1|content|content|||100|45,400,50,40,40,1;",other));
 // Dismissing while Cross is held cannot reinterpret a row as a toolbar press.
 chrome.input(8,950,120);chrome.input(0,950,120);chrome.input(1,950,123);
 chrome.input(1|16,1210,60);chrome.input(0,1210,60);assert(!chrome.take(out,sizeof(out)));assert(!chrome.modal());
 // Options advertises initial New Tab focus. Cross without pointer motion
 // or a preceding D-pad press must activate that exact row, not dismiss.
 chrome.input(8,500,500);chrome.input(0,500,500);
 chrome.input(1,500,500);chrome.input(0,500,500);
 assert(chrome.take(out,sizeof(out))&&!strcmp(out,"8:"));assert(!chrome.modal());
 // Full bounded queue: reject further commands, never overwrite accepted work.
 for(int i=0;i<20;++i){chrome.input(1024,800,500);chrome.input(0,800,500);}int n=0;while(chrome.take(out,sizeof(out)))++n;assert(n==16);
}
'''
  with tempfile.TemporaryDirectory() as directory:
   path=pathlib.Path(directory);(path/'test.cpp').write_text(source);binary=path/'test'
   command=['g++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-pthread','-I'+str(ROOT/'include'),str(path/'test.cpp'),str(ROOT/'src/native_chrome.cpp'),str(ROOT/'src/surface.cpp'),'-o',str(binary)]
   build=subprocess.run(command,capture_output=True,text=True);self.assertEqual(build.returncode,0,build.stdout+build.stderr)
   run=subprocess.run([str(binary)],capture_output=True,text=True);self.assertEqual(run.returncode,0,run.stdout+run.stderr)
