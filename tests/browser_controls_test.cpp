#include "orbisfox/browser_controls.h"
#include <cassert>
int main() {
  constexpr unsigned raw[] = {0x4000,0x1000,0x8000,8,0x2000,0x80,0x20,0x10,0x40,0x400,0x800,0x200,0x100,4,2};
  for (unsigned cycle=0;cycle<32;++cycle) {
    for (unsigned i=0;i<15;++i) {
      assert(orbisfox::browser_buttons(raw[i],true)==(1u<<i));
      assert(orbisfox::browser_buttons(raw[i],false)==(i<3?(1u<<i):0));
    }
    for(unsigned value=0;value<65536;++value) {
      assert(orbisfox::browser_buttons(value,true)<=32767);
      assert(orbisfox::browser_buttons(value,false)<=7);
      assert(orbisfox::browser_exit_chord(value,true)==((value&8)&&(value&0x2000)));
      assert(orbisfox::browser_exit_chord(value,false)==bool(value&8));
    }
    assert(!orbisfox::browser_exit_chord(8,true));
    assert(orbisfox::browser_exit_chord(0x2008,true));
  }
}
