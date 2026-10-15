#pragma once
#include <stdint.h>
namespace orbisfox {
struct ScrollDelta { int32_t x=0,y=0; };
// Pixel wheel deltas: clock-scaled, quadratic fine control, independent axes.
// Late frames discard backlog; neutral/disconnect discard fractional carry.
class StickScroll {
  uint64_t last_=0;
  int64_t carryX_=0,carryY_=0;
  static int axis(uint8_t value,uint64_t elapsed,int64_t& carry) {
    const int delta=int(value)-128, magnitude=delta<0?-delta:delta;
    if(magnitude<18){carry=0;return 0;}
    const int velocity=(magnitude-17)*(magnitude-17)/8*(delta<0?-1:1);
    if((carry<0 && velocity>0)||(carry>0 && velocity<0))carry=0;
    const int64_t pixels=velocity*int64_t(elapsed)+carry;
    carry=pixels%1000000;return int(pixels/1000000);
  }
public:
  void reset() {last_=0;carryX_=carryY_=0;}
  ScrollDelta update(uint8_t x,uint8_t y,uint64_t now) {
    const uint64_t elapsed=last_ && now>last_ ? (now-last_>32000?32000:now-last_) : 0;
    last_=now;
    return {axis(x,elapsed,carryX_),axis(y,elapsed,carryY_)};
  }
};
}
