// SPDX-License-Identifier: MIT
// Replay retained API geometry with the genuine SDK allocator and synthetic data.
// Not replay of browser writes, original addresses, timing, or firmware mappings.
#define ORBISFOX_SDK_ALLOCATOR_BACKEND_ONLY
#include "native_allocator_test.cpp"
#include "orbisfox/allocator_flight.h"
#include <array>
#include <fstream>
#include <unordered_map>
#include <vector>
extern "C" void sdk_test_advice_gate();
namespace orbisfox {
bool native_diagnostics_enabled(){return false;}
unsigned long long native_diagnostics_generation(){return 1;}
bool native_write_allocator_flight(const AllocatorFlightEvent*,size_t,unsigned long long,bool){return true;}
void native_write_heap_audit(const char* p,size_t n){(void)write(STDERR_FILENO,p,n);}
}
namespace {
struct Block {void* pointer;size_t requested,capacity;unsigned char pattern;};
std::unordered_map<uint64_t,Block> blocks;
uint64_t sequence=0, replayed=0, skipped=0, seeds=0, allocations=0, checked=0;
void check(bool okay,const char* why){
 if(okay)return;
 fprintf(stderr,"SDK flight replay FAILED: sequence=%llu: %s\n",(unsigned long long)sequence,why);
 abort();
}
void validate(const Block& b,size_t n){
 const auto* p=static_cast<const unsigned char*>(b.pointer);
 for(size_t i=0;i<n;++i)check(p[i]==b.pattern,"synthetic live payload overwritten");
 ++checked;
}
void remember(uint64_t identity,void* pointer,size_t bytes,bool zero){
 check(pointer!=nullptr,"recorded successful allocation failed on host");
 check(!blocks.contains(identity),"recorded address still live in retained replay");
 const size_t capacity=__wrap_malloc_usable_size(pointer);
 check(capacity>=bytes,"SDK capacity below request");
 if(zero){const auto* p=static_cast<const unsigned char*>(pointer);for(size_t i=0;i<bytes;++i)check(!p[i],"calloc did not zero requested bytes");}
 const auto pattern=static_cast<unsigned char>((++allocations*53u)%251u+1u);
 // Exercise storage advertised by the allocator, including legitimate slop.
 memset(pointer,pattern,capacity);
 blocks.emplace(identity,Block{pointer,bytes,capacity,pattern});
}
void replay(const orbisfox::AllocatorFlightEvent& e){
 if(e.phase!=2||e.depth!=1)return;
 sequence=e.sequence;
 const size_t n=e.bytes;auto it=blocks.find(e.input);
 switch(e.operation){
 case 1: case 2: case 6: case 7: case 8: case 9: case 10:{
  if(!e.output){++skipped;break;}
  void* p=nullptr;
  switch(e.operation){
   case 1:p=__wrap_malloc(n);break;
   case 2:p=__wrap_calloc(e.extra?e.extra:1,e.extra?n/e.extra:n);break;
   case 6:p=__wrap_memalign(e.extra,n);break;
   case 7:p=__wrap___memalign(e.extra,n);break;
   case 8:p=__wrap_aligned_alloc(e.extra,n);break;
   case 9:check(!__wrap_posix_memalign(&p,e.extra,n),"posix_memalign failed");break;
   case 10:p=__wrap_valloc(n);break;
  }
  remember(e.output,p,n,e.operation==2);++replayed;break;
 }
 case 3:{
  if(!e.output){check(n!=0,"zero-size realloc ownership ambiguous");++skipped;break;}
  if(e.input&&it==blocks.end()){
   // Its old allocation predates the retained window. Seed the new lifetime,
   // do not invent a prior request/copy or label it a replayed realloc.
   remember(e.output,__wrap_malloc(n),n,false);++seeds;break;
  }
  Block old{};if(it!=blocks.end()){old=it->second;validate(old,old.capacity);}
  void* p=__wrap_realloc(old.pointer,n);
  check(p!=nullptr,"recorded successful realloc failed on host");
  if(old.pointer){validate(Block{p,n,0,old.pattern},old.requested<n?old.requested:n);blocks.erase(it);}
  remember(e.output,p,n,false);++replayed;break;
 }
 case 4:
  if(!e.input){__wrap_free(nullptr);++replayed;break;}
  if(it==blocks.end()){++skipped;break;}
  validate(it->second,it->second.capacity);__wrap_free(it->second.pointer);blocks.erase(it);++replayed;break;
 case 5:
  if(it==blocks.end()){++skipped;break;}
  check(__wrap_malloc_usable_size(it->second.pointer)>=it->second.requested,"capacity shrank without realloc");++replayed;break;
 default:break; // Private SDK leaves occur inside the genuine implementation.
 }
}
}
int main(int argc,char** argv){
 if(argc!=2){fprintf(stderr,"usage: sdk-flight-replay allocator-flight.bin\n");return 2;}
 std::ifstream file(argv[1],std::ios::binary);
 std::array<uint64_t,8> header{};file.read(reinterpret_cast<char*>(header.data()),sizeof(header));
 check(bool(file),"short header");
 check(header[0]==orbisfox::allocatorFlightMagic&&header[1]==1&&header[2]==64,"bad format");
 const uint64_t capacity=header[3],committed=header[4];
 check(capacity>0&&capacity<=orbisfox::allocatorFlightCapacity,"invalid capacity");
 std::vector<orbisfox::AllocatorFlightEvent> events(capacity);
 file.read(reinterpret_cast<char*>(events.data()),capacity*sizeof(events[0]));check(bool(file),"short trace");
 check(orbisfox::initialize_native_allocator_lock(),"allocator lock init");
 sdk_test_thread_flag(std::getenv("SDK_TEST_BIN_LOCKS")?1:0);sdk_test_advice_gate();
 orbisfox::configure_native_allocator_bin_audit(true);
 const uint64_t first=committed>=capacity?committed-capacity+1:1;
 for(uint64_t i=first;i<=committed;++i){
  const auto& e=events[(i-1)%capacity];sequence=i;
  check(e.sequence==i&&e.checksum==orbisfox::allocator_flight_checksum(e),"sequence/checksum mismatch");
  check(e.bytes<=512u*1024u*1024u,"request exceeds host replay bound");
  replay(e);
 }
 const auto remaining=blocks.size();
 for(const auto& entry:blocks){validate(entry.second,entry.second.capacity);__wrap_free(entry.second.pointer);}
 printf("SDK retained flight replay PASS: first=%llu last=%llu operations=%llu seeds=%llu skipped=%llu payload-checks=%llu live-at-end=%zu; synthetic data, Linux shims, no firmware/GPU/write replay\n",
  (unsigned long long)first,(unsigned long long)committed,(unsigned long long)replayed,
  (unsigned long long)seeds,(unsigned long long)skipped,(unsigned long long)checked,remaining);
}
