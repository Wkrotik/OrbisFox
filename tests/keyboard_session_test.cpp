// Actual session policy; explicit firmware dialog doubles (not console proof).
#include "orbisfox/keyboard_session.h"
#include <cassert>
#include <cstring>
#include <initializer_list>
using namespace orbisfox;
struct Fake {
  bool ready=true;int user=7,initRC=0,status=1,resultRC=0,end=0,termRC=0;
  unsigned inits=0,terms=0,results=0;uint64_t time=1;char16_t* buffer=nullptr;
  KeyboardBackend backend() {return {this,
    [](void* p,int32_t* user){auto& f=*static_cast<Fake*>(p);*user=f.user;return f.ready;},
    [](void* p,int32_t user,char16_t* buffer,uint32_t limit){auto& f=*static_cast<Fake*>(p);assert(user==f.user&&limit==512);f.buffer=buffer;++f.inits;return f.initRC;},
    [](void* p){return static_cast<Fake*>(p)->status;},
    [](void* p,int32_t* end){auto& f=*static_cast<Fake*>(p);++f.results;*end=f.end;return f.resultRC;},
    [](void* p){auto& f=*static_cast<Fake*>(p);++f.terms;return f.termRC;},
    [](void* p){return static_cast<Fake*>(p)->time;}};}
};
int main() {
  for(unsigned cycle=0;cycle<32;++cycle) {
    Fake f;KeyboardSession session(f.backend());
    assert(session.poll()==KeyboardSession::Idle);
    assert(session.open(u"home",4));assert(!session.open(u"second",6));
    assert(session.active()&&session.poll()==KeyboardSession::Running);
    f.buffer[0]=u'x';f.status=2;
    assert(session.poll()==KeyboardSession::Accepted);assert(!session.active());assert(session.text()[0]==u'x');
    assert(f.terms==1&&f.results==1);session.poll();assert(f.results==1);
    assert(session.open(u"",0));assert(session.cancel());assert(session.cancel());assert(f.terms==2);
    for(int reason: {1,2,3,-1}) {
      Fake bad;KeyboardSession cancelled(bad.backend());assert(cancelled.open(u"home",4));bad.end=reason;bad.status=2;
      assert(cancelled.poll()==((reason==1||reason==2)?KeyboardSession::Cancelled:KeyboardSession::Error));
    }
    for(unsigned fault=0;fault<6;++fault) {
      Fake bad;KeyboardSession failed(bad.backend());assert(failed.open(u"home",4));
      if(fault==0)bad.status=-7;
      if(fault==1)bad.time+=300000001;
      if(fault==2){bad.status=2;bad.resultRC=-1;}
      if(fault==3){bad.status=2;bad.termRC=-1;}
      if(fault==4){bad.status=2;for(size_t i=0;i<=512;++i)bad.buffer[i]=u'a';}
      if(fault==5){bad.status=2;bad.buffer[0]=0xd800;bad.buffer[1]=0;}
      assert(failed.poll()==KeyboardSession::Error);
      if(fault==3){assert(failed.active());assert(!failed.open(u"",0));bad.termRC=0;assert(failed.cancel());assert(!failed.active());}
    }
    for(unsigned fault=0;fault<4;++fault){
      Fake bad;if(fault==0)bad.ready=false;if(fault==1)bad.user=-1;if(fault==2)bad.initRC=-1;if(fault==3)bad.initRC=1;
      KeyboardSession failed(bad.backend());assert(!failed.open(u"home",4));assert(!failed.active());
    }
    assert(!KeyboardSession::valid(nullptr,0));assert(!KeyboardSession::valid(u"a\0b",3));
    assert(!KeyboardSession::valid(u"a\nb",3));assert(!KeyboardSession::valid(u"🦊",1));
    assert(KeyboardSession::valid(u"🦊",2));
    char16_t maximum[514]{};for(unsigned i=0;i<513;++i)maximum[i]=u'a';
    assert(KeyboardSession::valid(maximum,512));assert(!KeyboardSession::valid(maximum,513));
  }
}
