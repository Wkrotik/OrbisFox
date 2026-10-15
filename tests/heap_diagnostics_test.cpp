#include "orbisfox/heap_diagnostics.h"
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <unordered_set>
using namespace orbisfox;
static std::unordered_set<void*> backing;
static std::vector<HeapDiagnosticEvent> events;
static std::string error;
static bool deny=false;
static unsigned char* corruptNext=nullptr;
alignas(64) static unsigned char reuse[1024];
static void* lastReleased=nullptr;
static void* reuseAllocate(size_t n){assert(n<=sizeof(reuse));return reuse;}
static void reuseRelease(void* p){lastReleased=p;}
static void* allocate(size_t n){if(deny){errno=ENOMEM;return nullptr;}void* p=std::malloc(n);assert(p);assert(backing.insert(p).second);if(corruptNext){*corruptNext^=1;corruptNext=nullptr;}return p;}
static void release(void* p){if(p){assert(backing.erase(p)==1);std::free(p);}}
static void event(const HeapDiagnosticEvent& e){events.push_back(e);}
static void fault(const char* message,const HeapDiagnosticEvent&){error=message;}
static auto backend(){return HeapDiagnosticBackend{allocate,release,event,fault};}
int main(){
 for(unsigned cycle=0;cycle<32;++cycle){
  error.clear();events.clear();HeapDiagnostics<64,4,4096> d;assert(d.enable(backend()));assert(!d.enable(backend()));
  auto make=[](size_t n){return allocate(n);};
  for(size_t n:{size_t(0),size_t(1),size_t(15),size_t(16),size_t(31),size_t(4097)}){
    void* p=d.allocate(n,16,0x111,make);assert(p&&uintptr_t(p)%16==0);
    assert(d.usable(p,0x112,[](void*){assert(false);return size_t(0);})==n);
    std::memset(p,0x31,n);void* q=d.reallocate(p,n+13,0x222,[](void*,size_t){assert(false);return nullptr;});assert(q);
    for(size_t j=0;j<n;++j)assert(static_cast<unsigned char*>(q)[j]==0x31);
    assert(d.release(q,0x333));assert(d.drain(0x444));
  }
  void* aligned=d.allocate(73,64,0x1,[](size_t n){void* p=nullptr;assert(!posix_memalign(&p,64,n));assert(backing.insert(p).second);return p;});assert(aligned&&uintptr_t(aligned)%64==0);assert(d.release(aligned,0x2));
  void* legacy=allocate(64);assert(d.release(legacy,0x3)); // Existing raw object; no prefix access.
  void* p=d.allocate(17,16,0x111,make);assert(p);deny=true;assert(!d.reallocate(p,128,0x222,[](void*,size_t){return nullptr;}));deny=false;assert(d.usable(p,0,[](void*){return size_t(0);})==17);
  assert(!d.allocate(SIZE_MAX,16,0,make));assert(!d.allocate(1,size_t(1)<<(sizeof(size_t)*8-1),0,make));
  assert(d.release(p,0x333));assert(d.drain(0));assert(d.active()==0&&d.quarantined()==0&&backing.empty());assert(error.empty());
  // Allocation boundaries are checked before the SDK gets a free request.
  p=d.allocate(16,16,0xa1,make);auto* bytes=static_cast<unsigned char*>(p);unsigned char old=bytes[16];bytes[16]^=1;
  assert(!d.release(p,0xb1));assert(error=="allocation suffix overwritten");bytes[16]=old;error.clear();
  old=bytes[-1];bytes[-1]^=1;assert(!d.release(p,0xb2));assert(error=="allocation prefix overwritten");bytes[-1]=old;error.clear();
  assert(d.release(p,0xb3));assert(!d.release(p,0xb4));assert(error=="double free in quarantine");error.clear();
  assert(!d.reallocate(p,1,0,[](void*,size_t){assert(false);return nullptr;}));assert(error=="realloc after free in quarantine");error.clear();
  bytes[0]=0;assert(!d.drain(0xb5));assert(error=="write after free in quarantine");bytes[0]=0xdd;error.clear();assert(d.drain(0));
  assert(d.active()==0&&backing.empty());
  HeapDiagnostics<4,1,128> small;assert(small.enable(backend()));void* held[3];
  static_assert(decltype(small)::trackingLimit()==3);
  for(auto& value:held){value=small.allocate(8,16,0,make);assert(value);}
  // Saturation changes coverage, not SDK allocation success. Return unshifted
  // raw pointers, preserve requested sizes, errno, existing guards and ownership.
  size_t request=0;errno=EAGAIN;
  void* untracked=small.allocate(19,16,0,[&](size_t n){request=n;return allocate(n);});
  assert(untracked&&request==19&&backing.count(untracked)==1&&errno==EAGAIN&&error.empty());
  assert(events[events.size()-2].operation==10&&events.back().operation==11);
  assert(small.active()==3&&small.usable(untracked,0,[](void*){return size_t(19);})==19);
  assert(small.release(untracked,0));
  void* zeroed=small.allocate(23,16,0,[&](size_t n){assert(n==23);void* raw=std::calloc(1,n);assert(raw&&backing.insert(raw).second);return raw;});
  for(unsigned i=0;i<23;++i)assert(static_cast<unsigned char*>(zeroed)[i]==0);
  assert(small.release(zeroed,0));
  void* fallbackAligned=small.allocate(64,64,0,[&](size_t n){assert(n==64);void* raw=nullptr;assert(!posix_memalign(&raw,64,n));assert(raw&&backing.insert(raw).second);return raw;});
  assert(uintptr_t(fallbackAligned)%64==0);assert(small.release(fallbackAligned,0));
  deny=true;assert(!small.allocate(19,16,0,make));deny=false;
  assert(events.back().operation==11&&events.back().pointer==0&&errno==ENOMEM&&small.active()==3);
  auto* oldGuard=static_cast<unsigned char*>(held[1]);oldGuard[8]^=1;
  assert(!small.release(held[1],0));assert(error=="allocation suffix overwritten");oldGuard[8]^=1;error.clear();
  memset(held[0],0x37,8);void* resized=small.reallocate(held[0],19,0,[](void*,size_t){assert(false);return nullptr;});
  assert(resized&&backing.count(resized));for(unsigned i=0;i<8;++i)assert(static_cast<unsigned char*>(resized)[i]==0x37);
  held[0]=resized;
  for(auto value:held)assert(small.release(value,0));
  assert(small.drain(0));assert(backing.empty());
  // Hash deletion and movable records must preserve every live/quarantined key
  // during repeated admission-limit churn, including pointer/record reuse.
  for(unsigned round=0;round<512;++round){
    for(auto& value:held){value=small.allocate(8,16,0,make);assert(value);}
    for(auto value:held)assert(small.release(value,0));
    assert(small.drain(0));
  }
  assert(backing.empty()&&error.empty());
  for(auto& value:held){value=small.allocate(8,16,0,make);assert(value);}
  auto* rollbackGuard=static_cast<unsigned char*>(held[0]);corruptNext=rollbackGuard+8;
  assert(!small.reallocate(held[0],19,0,[](void*,size_t){assert(false);return nullptr;}));
  assert(error=="allocation suffix overwritten"&&backing.size()==3&&small.active()==3);
  assert(events.back().operation==6&&events.back().backing==0);rollbackGuard[8]^=1;error.clear();
  for(auto value:held)assert(small.release(value,0));
  assert(small.drain(0)&&backing.empty());
  HeapDiagnostics<16,1,128> rollback;assert(rollback.enable(backend()));
  auto* a=static_cast<unsigned char*>(rollback.allocate(8,16,0,make));void* b=rollback.allocate(8,16,0,make);
  assert(rollback.release(a,0));a[0]=0;
  assert(!rollback.reallocate(b,16,0,[](void*,size_t){assert(false);return nullptr;}));
  assert(error=="write after free in quarantine");assert(rollback.active()==1&&backing.size()==2);error.clear();a[0]=0xdd;
  assert(rollback.release(b,0));assert(rollback.drain(0));assert(backing.empty());
  // A retired payload may become a legitimate raw SDK allocation. Unknown raw
  // ownership is passed through, never diagnosed from an old address alone.
  HeapDiagnostics<4,1,128> collision;assert(collision.enable({reuseAllocate,reuseRelease,event,fault}));
  void* former=collision.allocate(32,16,0,reuseAllocate);assert(collision.release(former,0));assert(collision.drain(0));assert(lastReleased==reuse);
  assert(collision.usable(former,0,[](void*){return size_t(32);})==32);
  assert(collision.reallocate(former,32,0,[](void* raw,size_t){return raw;})==former);
  assert(collision.release(former,0));assert(lastReleased==former&&error.empty());
 }
}
