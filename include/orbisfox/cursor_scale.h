#pragma once
namespace orbisfox {
class CursorScale {
  double carry_=0;
 public:
  void reset(){carry_=0;}
  int update(int delta,double multiplier){
    if(!delta){reset();return 0;}
    if(!(multiplier>=0.25 && multiplier<=3.0))multiplier=1;
    const double scaled=delta*multiplier+carry_;
    const int result=static_cast<int>(scaled);carry_=scaled-result;return result;
  }
};
}
