#pragma once
#include "orbisfox/surface.h"
#include <pthread.h>
#include <atomic>
namespace orbisfox {
struct ChromeControl {int command=0,x=0,y=0,width=0,height=0;bool enabled=false;};
struct ChromeScene {
 bool enabled=false,fullscreen=false,web=false;char active[32]{},tabs[3][32]{};
 ChromeControl controls[20]{};unsigned count=0,zoom=100;
};
// Main supplies bounded layout/state, never DOM pointers. Worker owns local
// menu/hover/pressed feedback; Gecko actions remain queued for its main thread.
bool parse_chrome_scene(const char* wire,ChromeScene& result);
// Main-only before worker start; bakes the trusted packaged OFL Noto font.
bool prepare_native_chrome_font(const char* path="/app0/assets/fonts/NotoSans-Regular.ttf");
class NativeChrome {
 pthread_mutex_t mutex_=PTHREAD_MUTEX_INITIALIZER;
 ChromeScene scene_{};
 char actions_[16][48]{};unsigned head_=0,count_=0;
 bool menu_=false,swallowPrimary_=false,swallowMiddle_=false,overflow_=false,keyboardMenu_=false;
 int menuPointerX_=-1,menuPointerY_=-1;
 unsigned menuFocus_=0;uint32_t previous_=0;
 int hover_=-1,pressed_=-1;char desiredTab_[32]{};
 std::atomic<uint64_t> revision_{0};
 bool push(int command,const char* target=nullptr);
 void activate(int command);
 public:
 ~NativeChrome();
 void update(const ChromeScene& scene); // main only; POD copy under lock
 uint32_t input(uint32_t buttons,int x,int y); // worker; normalized buttons
 void render(Surface surface); // worker; owned output pixels only
 bool take(char* destination,size_t capacity); // main; actual command, not eval
 bool modal(); // Independent of shortcut/edge masks; worker scroll admission.
 uint64_t revision() const {return revision_.load();}
};
}
