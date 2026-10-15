#include "orbisfox/stick_scroll.h"
#include <cassert>
#include <cstdlib>
using namespace orbisfox;
int main() {
  for(unsigned cycle=0;cycle<32;++cycle) {
    for(unsigned value=0;value<256;++value) {
      StickScroll scroll;int64_t x=0,y=0;uint64_t now=1;
      assert(scroll.update(value,128,now).x==0);
      for(unsigned frame=0;frame<1000;++frame) {
        now+=16000;const auto delta=scroll.update(value,128,now);
        assert(delta.y==0&&std::abs(delta.x)<=64);x+=delta.x;y+=delta.y;
      }
      assert(y==0);const int d=int(value)-128,magnitude=std::abs(d);
      if(magnitude<18)assert(x==0);
      else assert(x==int64_t((magnitude-17)*(magnitude-17)/8)*(d<0?-16:16));
      const auto neutral=scroll.update(128,128,now+16000);assert(neutral.x==0&&neutral.y==0);
      const auto stalled=scroll.update(255,0,now+10000000);assert(stalled.x<=64&&stalled.y>=-64);
      scroll.reset();const auto restart=scroll.update(0,255,now+20000000);assert(restart.x==0&&restart.y==0);
    }
    StickScroll a,b;a.update(255,128,1);b.update(128,255,1);
    for(unsigned frame=1;frame<=100;++frame)assert(a.update(255,128,1+frame*16000).x==b.update(128,255,1+frame*16000).y);
    StickScroll fast,slow;fast.update(255,255,1);slow.update(255,255,1);int f=0,s=0;
    for(unsigned frame=1;frame<=200;++frame)f+=fast.update(255,255,1+frame*8000).x;
    for(unsigned frame=1;frame<=100;++frame)s+=slow.update(255,255,1+frame*16000).x;
    assert(f==s);
  }
}
