#include "orbisfox/keyboard_launch.h"
#include <cassert>
#include <string.h>
using namespace orbisfox;
int main(){
  for(unsigned cycle=0;cycle<32;++cycle){
    KeyboardLaunch gate;unsigned opens=0;
    auto open=[&](const char16_t* text,uint32_t length,bool address){assert(length==4&&text[0]==u'h'&&text[4]==0&&address);++opens;return true;};
    char16_t draft[]=u"home";assert(gate.queue(draft,4,true,0));draft[0]=u'x';assert(!gate.queue(u"next",4,false,0));
    gate.tick(0x4000,1,open);gate.tick(0,2,open);assert(gate.pending()&&opens==0);gate.tick(0x8000,3,open);
    gate.tick(0,4,open);assert(gate.pending());gate.tick(0,5,open);assert(!gate.pending()&&!gate.failed()&&opens==1);gate.tick(0,6,open);assert(opens==1);
    assert(gate.queue(u"home",4,true,10));gate.cancel();gate.tick(0,11,open);assert(opens==1&&!gate.failed());
    assert(gate.queue(u"home",4,true,100));gate.tick(UINT32_MAX,5000100,open);assert(gate.failed()&&!gate.pending()&&opens==1);
    assert(gate.queue(u"home",4,false,200));gate.tick(0,201,open);gate.tick(0,202,[](const char16_t*,uint32_t,bool address){assert(!address);return false;});assert(gate.failed());
    assert(!gate.queue(u"\n",1,true,0));assert(!gate.queue(nullptr,0,true,0));assert(!gate.queue(u"bad",513,true,0));
  }
}
