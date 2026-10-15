#pragma once
#include "orbisfox/keyboard_session.h"
namespace orbisfox {
// Delay actual system-dialog activation until two controller samples show no
// held buttons. A queued launch is not firmware initialization success.
class KeyboardLaunch {
  char16_t draft_[KeyboardSession::limit+1]{};
  uint32_t length_=0;
  unsigned released_=0;
  bool pending_=false,failed_=false,address_=true;
  uint64_t deadline_=0;
public:
  bool queue(const char16_t* text,uint32_t length,bool address,uint64_t now){
    if(pending_||!KeyboardSession::valid(text,length))return false;
    for(size_t i=0;i<=KeyboardSession::limit;++i)draft_[i]=i<length?text[i]:0;
    length_=length;address_=address;released_=0;pending_=true;failed_=false;deadline_=now+UINT64_C(5000000);return true;
  }
  template<typename Open> void tick(uint32_t buttons,uint64_t now,Open open){
    if(!pending_)return;
    if(now>=deadline_){pending_=false;failed_=true;return;}
    if(buttons){released_=0;return;}
    if(++released_<2)return;
    pending_=false;failed_=!open(draft_,length_,address_);
  }
  void cancel(){pending_=failed_=false;released_=0;}
  bool pending()const{return pending_;}
  bool failed()const{return failed_;}
};
}
