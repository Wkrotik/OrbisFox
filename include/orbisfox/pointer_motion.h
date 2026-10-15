#pragma once
#include <stdint.h>
#include "orbisfox/stick_cursor.h"
namespace orbisfox {
struct PointerPollTiming {uint64_t elapsed=0;bool discontinuity=false;};
class PointerPollClock {
  uint64_t last_=0;
 public:
  void reset(){last_=0;}
  PointerPollTiming update(uint64_t now){
    const uint64_t previous=last_;last_=now;
    if(!previous)return {};
    if(now<=previous || now-previous>64000)return {0,true};
    // Never accumulate movement for time spent blocked in page code.
    return {now-previous>16000?16000:now-previous,false};
  }
};
class TimedStickCursor {
  double carry_=0;
 public:
  void reset(){carry_=0;}
  int update(uint8_t value,double multiplier,uint64_t elapsed){
    const int delta=stick_cursor_delta(value);
    if(!delta || !elapsed){reset();return 0;}
    if(!(multiplier>=0.25 && multiplier<=3.0))multiplier=1;
    if(elapsed>16000)elapsed=16000;
    if((carry_<0 && delta>0)||(carry_>0 && delta<0))reset();
    const double pixels=delta*1.5*multiplier*(double(elapsed)/16000.0)+carry_;
    const int whole=static_cast<int>(pixels);carry_=pixels-whole;return whole;
  }
};
}
