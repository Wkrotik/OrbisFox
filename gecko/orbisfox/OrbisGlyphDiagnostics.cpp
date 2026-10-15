#include "OrbisGlyphDiagnostics.h"
#include <atomic>
namespace orbisfox {
namespace {std::atomic<uint64_t> draws{0};std::atomic<uint32_t> codepoints[64]{};}
void record_missing_glyph(uint32_t codepoint){
 draws.fetch_add(1,std::memory_order_relaxed);
 if(!codepoint || codepoint>0x10ffff)return;
 for(auto& slot:codepoints){
  uint32_t current=slot.load(std::memory_order_relaxed);
  if(current==codepoint)return;
  if(!current && slot.compare_exchange_strong(current,codepoint,std::memory_order_relaxed))return;
  if(current==codepoint)return;
 }
}
MissingGlyphStats missing_glyph_stats(){
 MissingGlyphStats result;result.draws=draws.load(std::memory_order_relaxed);
 for(unsigned i=0;i<64;++i)result.codepoints[i]=codepoints[i].load(std::memory_order_relaxed);
 return result;
}
}
