#include "orbisfox/surface.h"
#include <cassert>
#include <vector>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <chrono>
using namespace orbisfox;
int main(){
  for(unsigned cycle=0;cycle<32;++cycle)for(unsigned w:{1u,3u,4u,7u,16u,17u,1279u,1280u}){
    const unsigned h=5,srcStride=w*4+7,dstStride=w*4+13,offset=1+cycle%16;
    std::vector<uint8_t> source(srcStride*h+32,0xa7),target(dstStride*h+32,0xd1),expected=target;
    for(size_t i=offset;i<source.size()-16;++i)source[i]=uint8_t(i*71+cycle);
    Surface dest{target.data()+offset,int(w),int(h),dstStride};
    for(unsigned y=0;y<h;++y)for(unsigned x=0;x<w;++x){
      const auto* p=source.data()+offset+y*srcStride+x*4;auto* q=expected.data()+offset+y*dstStride+x*4;
      q[0]=p[2];q[1]=p[1];q[2]=p[0];q[3]=255;
    }
    assert(blit_bgra_opaque(dest,source.data()+offset,w,h,srcStride));assert(target==expected);
    std::vector<uint8_t> converted(w*h*4+32,0x63),reference=converted;
    for(unsigned y=0;y<h;++y)for(unsigned x=0;x<w;++x){
      const auto* p=target.data()+offset+y*dstStride+x*4;auto* q=reference.data()+offset+(y*w+x)*4;
      q[0]=p[2];q[1]=p[1];q[2]=p[0];q[3]=p[3];
    }
    rgba_to_bgra(converted.data()+offset,dest);assert(converted==reference);
    const auto unchanged=target;
    assert(!blit_bgra_opaque(dest,nullptr,w,h,srcStride));assert(!blit_bgra_opaque(dest,source.data(),w+1,h,srcStride));
    assert(!blit_bgra_opaque(dest,source.data(),w,h+1,srcStride));assert(!blit_bgra_opaque(dest,source.data(),w,h,w*4-1));
    assert(!blit_bgra_opaque(dest,source.data(),0,h,srcStride));assert(target==unchanged);
  }
  // Alpha-preserving scanout conversion must also match non-opaque sources.
  std::vector<uint8_t> alpha(128),out(128);for(unsigned i=0;i<128;++i)alpha[i]=uint8_t(i*37);
  rgba_to_bgra(out.data(),Surface{alpha.data(),32,1,128});for(unsigned x=0;x<32;++x){assert(out[x*4]==alpha[x*4+2]);assert(out[x*4+3]==alpha[x*4+3]);}
  std::vector<uint8_t> in(1280*720*4),pixels(in.size());for(size_t i=0;i<in.size();++i)in[i]=uint8_t(i);
  auto start=std::chrono::steady_clock::now();for(unsigned i=0;i<240;++i)assert(blit_bgra_opaque(Surface{pixels.data(),1280,720,5120},in.data(),1280,720,5120));
  auto us=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-start).count();
  std::printf("Pixel blit:32 cycles padded/unaligned/odd widths and guards/alpha PASS; host1280x720 mean=%lldus (not PS4 or end-to-end FPS)\n",static_cast<long long>(us/240));
}
