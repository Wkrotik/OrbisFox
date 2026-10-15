#pragma once
#include <stddef.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>

namespace orbisfox {
// Development-only bookkeeping around the existing SDK heap. Callers hold the
// native recursive heap mutex. No internal allocation, stdio, or private libc
// field writes. A quarantine retains genuinely allocated blocks to detect stale
// writes before the SDK reuses their payload as free-list links.
struct HeapDiagnosticEvent {
  uint64_t sequence, operation, pointer, backing, size, caller, allocatedAt, freedAt;
};
struct HeapDiagnosticBackend {
  void* (*malloc)(size_t);
  void (*free)(void*);
  void (*event)(const HeapDiagnosticEvent&);
  void (*fault)(const char*,const HeapDiagnosticEvent&);
};
template<size_t Capacity, size_t QuarantineSlots, size_t QuarantineBytes>
class HeapDiagnostics {
  static_assert(Capacity>1 && (Capacity&(Capacity-1))==0);
  static_assert(QuarantineSlots>0);
  enum State:uint8_t {Empty,Live,Held};
  struct Record {
    void* user=nullptr; void* raw=nullptr; size_t size=0,total=0;
    uintptr_t allocated=0,freed=0; uint64_t serial=0; State state=Empty;
  };
  Record records_[Capacity]{};
  void* queue_[QuarantineSlots]{};
  size_t head_=0,count_=0,heldBytes_=0,active_=0;
  uint64_t serial_=0,sequence_=0;
  HeapDiagnosticBackend backend_{};
  bool enabled_=false;
  static constexpr size_t guard=16;
  // Reserve empty hash buckets: absent/raw-pointer lookups must not scan a
  // completely full table while holding the process-wide heap mutex.
  static constexpr size_t admissionLimit=Capacity-(Capacity/4?Capacity/4:1);
  static uint8_t byte(uint64_t serial,unsigned i,bool tail){return uint8_t(serial>>(8*(i%8)))^uint8_t(i*23)^(tail?0x5a:0xa5);}
  static size_t hash(void* p){uintptr_t v=reinterpret_cast<uintptr_t>(p)>>4;v^=v>>17;v*=uintptr_t(0x9e3779b1);return size_t(v)&(Capacity-1);}
  Record* find(void* p){
    if(!p)return nullptr;
    size_t at=hash(p);
    for(size_t i=0;i<Capacity;++i){auto& r=records_[(at+i)&(Capacity-1)];if(r.state==Empty)return nullptr;if(r.user==p)return &r;}
    return nullptr;
  }
  Record* slot(void* p){
    size_t at=hash(p);
    for(size_t i=0;i<Capacity;++i){auto& r=records_[(at+i)&(Capacity-1)];if(r.state==Empty||r.user==p)return &r;}
    return nullptr;
  }
  void erase(Record& record){
    // Backshift deletion keeps probe chains intact without accumulating retired
    // keys. Quarantine entries name payloads, not movable record addresses.
    size_t hole=size_t(&record-records_);records_[hole]={};
    for(size_t at=(hole+1)&(Capacity-1),visited=0;visited<Capacity-1;++visited,at=(at+1)&(Capacity-1)){
      if(records_[at].state==Empty)break;
      const size_t home=hash(records_[at].user);
      if(((hole-home)&(Capacity-1))<((at-home)&(Capacity-1))){records_[hole]=records_[at];records_[at]={};hole=at;}
    }
  }
  void discard(void* pointer,uintptr_t caller){
    auto* r=find(pointer);
    if(!r){event(6,nullptr,pointer,0,caller);backend_.free(pointer);return;}
    event(6,r,pointer,r->size,caller);backend_.free(r->raw);--active_;erase(*r);
  }
  HeapDiagnosticEvent event(uint64_t operation,Record* r,void* pointer,size_t size,uintptr_t caller){
    HeapDiagnosticEvent e{++sequence_,operation,reinterpret_cast<uintptr_t>(pointer),r?reinterpret_cast<uintptr_t>(r->raw):0,size,caller,r?r->allocated:0,r?r->freed:0};
    if(backend_.event)backend_.event(e);
    return e;
  }
  bool fault(const char* text,Record* r,void* p,size_t size,uintptr_t caller){
    auto e=event(9,r,p,size,caller);if(backend_.fault)backend_.fault(text,e);return false;
  }
  void mark(Record& r){auto* p=static_cast<uint8_t*>(r.user);for(unsigned i=0;i<guard;++i){p[-ptrdiff_t(guard)+i]=byte(r.serial,i,false);p[r.size+i]=byte(r.serial,i,true);}}
  bool valid(Record& r,uintptr_t caller){
    const auto* p=static_cast<const uint8_t*>(r.user);
    for(unsigned i=0;i<guard;++i){
      if(p[-ptrdiff_t(guard)+i]!=byte(r.serial,i,false))return fault("allocation prefix overwritten",&r,r.user,r.size,caller);
      if(p[r.size+i]!=byte(r.serial,i,true))return fault("allocation suffix overwritten",&r,r.user,r.size,caller);
    }
    return true;
  }
  bool evict(uintptr_t caller){
    if(!count_)return true;
    auto& r=*find(queue_[head_]);
    if(!valid(r,caller))return false;
    const auto* p=static_cast<const uint8_t*>(r.user);
    for(size_t i=0;i<r.size;++i)if(p[i]!=0xdd)return fault("write after free in quarantine",&r,r.user,r.size,caller);
    event(5,&r,r.user,r.size,caller);backend_.free(r.raw);heldBytes_-=r.total;erase(r);
    head_=(head_+1)%QuarantineSlots;--count_;return true;
  }
public:
  bool enable(HeapDiagnosticBackend backend){
    if(enabled_||!backend.malloc||!backend.free||!backend.fault)return false;
    backend_=backend;enabled_=true;return true;
  }
  bool enabled()const{return enabled_;}
  size_t active()const{return active_;}
  size_t quarantined()const{return count_;}
  static constexpr size_t trackingLimit(){return admissionLimit;}
  // make(total) calls the genuine original SDK allocation API. Nested SDK
  // allocator calls must bypass these diagnostics under the outer heap lock.
  template<class Make> void* allocate(size_t size,size_t alignment,uintptr_t caller,Make make){
    if(alignment<guard)alignment=guard;
    if((alignment&(alignment-1)) || alignment>SIZE_MAX/2 || size>SIZE_MAX-alignment-guard-(alignment-1)){errno=ENOMEM;return nullptr;}
    const size_t offset=alignment,total=(offset+size+guard+alignment-1)&~(alignment-1);
    event(1,nullptr,nullptr,size,caller);
    while(active_+count_>=admissionLimit&&count_)if(!evict(caller))return nullptr;
    if(active_+count_>=admissionLimit){
      // Diagnostic bookkeeping is not a resource prerequisite for Gecko. Keep
      // all existing guards, but let the genuine SDK handle new raw pointers
      // with the original request. Never return an unrecorded shifted pointer.
      event(10,nullptr,nullptr,size,caller);
      void* raw=make(size);event(11,nullptr,raw,size,caller);return raw;
    }
    void* raw=make(total);if(!raw)return nullptr;
    void* user=static_cast<uint8_t*>(raw)+offset;auto* r=slot(user);
    // Admission reserves empty buckets, so failure here is an internal invariant
    // violation, not ordinary capacity pressure. Do not silently lose ownership.
    if(!r){fault("diagnostic ownership table invariant failed",nullptr,user,size,caller);return nullptr;}
    if(r->state==Live||r->state==Held){fault("SDK returned an overlapping live pointer",r,user,size,caller);return nullptr;}
    *r={user,raw,size,total,caller,0,++serial_,Live};++active_;mark(*r);event(2,r,user,size,caller);return user;
  }
  bool release(void* pointer,uintptr_t caller){
    if(!pointer){backend_.free(nullptr);return true;}auto* r=find(pointer);
    if(!r){event(7,nullptr,pointer,0,caller);backend_.free(pointer);return true;} // Pre-enable/external SDK-owned object.
    // After eviction, the SDK can reuse/split a backing block into a raw
    // allocation at the former payload address. Retired addresses alone cannot
    // prove stale ownership; definitive stale checks stop at quarantine.
    if(r->state!=Live)return fault("double free in quarantine",r,pointer,r->size,caller);
    if(!valid(*r,caller))return false;
    r->freed=caller;event(3,r,pointer,r->size,caller);
    if(r->total>QuarantineBytes){backend_.free(r->raw);--active_;erase(*r);return true;}
    const size_t total=r->total;
    while(count_==QuarantineSlots||heldBytes_>QuarantineBytes-total)if(!evict(caller))return false;
    // Eviction may backshift the old record; reacquire it by stable payload.
    r=find(pointer);memset(r->user,0xdd,r->size);r->state=Held;--active_;queue_[(head_+count_)%QuarantineSlots]=pointer;++count_;heldBytes_+=r->total;return true;
  }
  // Intentional diagnostic policy: copy into genuine SDK malloc storage and
  // quarantine the old allocation. This differs from direct SDK realloc, so a
  // disappearing crash alone is NOT evidence of a client/SDK root cause.
  template<class Original> void* reallocate(void* pointer,size_t size,uintptr_t caller,Original original){
    if(!pointer)return allocate(size,guard,caller,[&](size_t total){return backend_.malloc(total);});
    auto* r=find(pointer);if(!r){
      event(8,nullptr,pointer,size,caller);return original(pointer,size);
    }
    if(r->state!=Live){fault("realloc after free in quarantine",r,pointer,size,caller);return nullptr;}
    if(!valid(*r,caller))return nullptr;
    const size_t oldSize=r->size;
    void* fresh=allocate(size,guard,caller,[&](size_t total){return backend_.malloc(total);});if(!fresh)return nullptr;
    memcpy(fresh,pointer,oldSize<size?oldSize:size);
    if(!release(pointer,caller)){discard(fresh,caller);return nullptr;}return fresh;
  }
  template<class Original> size_t usable(void* pointer,uintptr_t caller,Original original){
    auto* r=find(pointer);if(!r)return original(pointer);
    if(r->state!=Live){fault("size query after free in quarantine",r,pointer,r->size,caller);return 0;}
    if(!valid(*r,caller))return 0;
    return r->size;
  }
  bool drain(uintptr_t caller){while(count_)if(!evict(caller))return false;return true;}
};
}
