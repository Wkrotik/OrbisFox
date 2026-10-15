#pragma once
#include <stdint.h>
#include <stddef.h>
namespace orbisfox {
// Native dialog doubles in host tests, genuine firmware functions in the app.
struct KeyboardBackend {
  void* context;
  bool (*prepare)(void*, int32_t*);
  int32_t (*init)(void*, int32_t, char16_t*, uint32_t);
  int32_t (*status)(void*);
  int32_t (*result)(void*, int32_t*);
  int32_t (*term)(void*);
  uint64_t (*now)(void*);
};
class KeyboardSession {
public:
  static constexpr size_t limit=512;
  enum Status : uint32_t { Idle=0, Running=1, Accepted=2, Cancelled=3, Error=4 };
private:
  KeyboardBackend backend_;
  char16_t text_[limit+1]{};
  bool active_=false;
  Status status_=Idle;
  uint64_t deadline_=0;
  bool terminate() {
    if (!active_) return true;
    if (backend_.term(backend_.context)!=0) return false;
    active_=false; return true;
  }
public:
  explicit KeyboardSession(KeyboardBackend backend):backend_(backend) {}
  static bool valid(const char16_t* text,size_t length) {
    if (!text || length>limit) return false;
    for(size_t i=0;i<length;++i) {
      const auto unit=text[i];
      if(unit<0x20 || unit==0x7f) return false;
      if(unit>=0xd800 && unit<=0xdbff) {
        if(++i>=length || text[i]<0xdc00 || text[i]>0xdfff) return false;
      } else if(unit>=0xdc00 && unit<=0xdfff) return false;
    }
    return true;
  }
  bool open(const char16_t* draft,size_t length) {
    if(active_ || !valid(draft,length)) return false;
    int32_t user=-1;
    if(!backend_.prepare(backend_.context,&user) || user<0) return false;
    for(size_t i=0;i<=limit;++i) text_[i]=i<length?draft[i]:0;
    if(backend_.init(backend_.context,user,text_,limit)!=0) return false;
    active_=true;status_=Running;
    deadline_=backend_.now(backend_.context)+UINT64_C(300000000);
    return true;
  }
  Status poll() {
    if(!active_) return status_;
    if(status_!=Running) return status_; // Failed termination: retain buffers/ownership.
    const auto native=backend_.status(backend_.context);
    if(native==1 && backend_.now(backend_.context)<deadline_) return Running;
    int32_t result=-1;
    const bool stopped=native==2;
    const bool got=stopped && backend_.result(backend_.context,&result)==0;
    const bool terminated=terminate();
    if(!got || !terminated || (result!=0 && result!=1 && result!=2)) return status_=Error;
    if(result!=0) return status_=Cancelled;
    size_t length=0;while(length<=limit && text_[length]) ++length;
    return status_=valid(text_,length)?Accepted:Error;
  }
  bool cancel() { const bool okay=terminate();status_=okay?Cancelled:Error;return okay; }
  bool active() const {return active_;}
  const char16_t* text() const {return text_;}
};
}
