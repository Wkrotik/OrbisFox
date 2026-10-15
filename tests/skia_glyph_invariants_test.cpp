// Actual extracted SkStrike::glyph and producer/consumer checks. Data/strike
// containers are doubles; this is NOT complete Skia font rendering coverage.
#include "include/private/base/SkMutex.h"
#include "include/core/SkPoint.h"
#include "src/base/SkZip.h"
#include <vector>
#include <thread>
#include <cassert>
#include <cstdio>
#include <cstdarg>
#include <cstdlib>
#include <csignal>
#include <sys/wait.h>
#include <unistd.h>
void SkDebugf(const char* fmt,...){va_list args;va_start(args,fmt);vfprintf(stderr,fmt,args);va_end(args);}
[[noreturn]] void sk_abort_no_print(){abort();}
bool sk_abort_is_enabled(){return true;}
struct SkGlyph {unsigned value;};
struct SkGlyphDigest {size_t i;size_t index() const{return i;}};
struct SkStrike {
  std::vector<SkGlyph*> fGlyphForIndex;
  SkMutex lock;
  SkGlyph* glyph(SkGlyphDigest digest);
};
/* ACTUAL_LOOKUP */
static void prepare(SkZip<const unsigned short,const SkPoint> source,
                    SkZip<const SkGlyph*,SkPoint> acceptedBuffer,
                    SkZip<unsigned short,SkPoint> rejectedBuffer) {
/* ACTUAL_PREPARE */
}
static void consume(SkZip<const SkGlyph*,SkPoint> accepted){
/* ACTUAL_CONSUME */
}
int main(){
  alarm(45);
  for(unsigned cycle=0;cycle<32;++cycle){
    SkGlyph glyphs[8*256]{};SkStrike strike;
    std::vector<std::thread> threads;
    for(unsigned t=0;t<8;++t)threads.emplace_back([&,t]{
      for(unsigned n=0;n<256;++n){
        SkAutoMutexExclusive hold(strike.lock);
        auto& glyph=glyphs[t*256+n];glyph.value=t*256+n;
        strike.fGlyphForIndex.push_back(&glyph);
        size_t i=strike.fGlyphForIndex.size()-1;
        std::this_thread::yield();assert(strike.glyph({i})==&glyph);
        assert(strike.glyph({i})->value==t*256+n);
      }
    });
    for(auto& thread:threads)thread.join();
    unsigned short ids[2]={1,2}, rejectedIDs[2]{};SkPoint positions[2]={{0,0},{8,8}}, out[2]{};
    const SkGlyph* accepted[2]={&glyphs[0],&glyphs[1]};
    prepare({2,ids,positions},{2,accepted,out},{2,rejectedIDs,out});
    consume({2,accepted,positions});
  }
  for(unsigned kind=0;kind<5;++kind){
    pid_t pid=fork();assert(pid>=0);
    if(pid==0){
      alarm(2);SkGlyph glyph{};SkStrike strike;strike.fGlyphForIndex={&glyph,nullptr};
      unsigned short ids[2]={1,2}, rejectedIDs[2]{};SkPoint positions[2]={{0,0},{8,8}};
      const SkGlyph* accepted[2]={&glyph,nullptr};
      if(kind==0)strike.glyph({2});
      if(kind==1)strike.glyph({1});
      if(kind==2)consume({2,accepted,positions});
      if(kind==3)prepare({2,ids,positions},{1,accepted,positions},{2,rejectedIDs,positions});
      if(kind==4)prepare({2,ids,positions},{2,accepted,positions},{1,rejectedIDs,positions});
      _exit(99);
    }
    int status=0;assert(waitpid(pid,&status,0)==pid);
    assert(WIFSIGNALED(status)&&WTERMSIG(status)==SIGABRT);
  }
  puts("Actual extracted glyph lookup / prepare / consume invariants: 32 x 8-worker cache growth, 5 fatal invalid cases PASS; explicit glyph/digest/container doubles, not full renderer/firmware");
}
