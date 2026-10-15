import pathlib
import shutil
import subprocess
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]

class AudioResamplerTest(unittest.TestCase):
    def test_real_cubeb_speex_rate_conversion_and_drain(self):
        cubeb = ROOT / '.deps/gecko-layout/media/libcubeb/src'
        speex = ROOT / '.deps/gecko-layout/media/libspeex_resampler/src'
        if not (speex / 'resample.c').is_file():
            self.skipTest('pinned Gecko source unavailable')
        source = r'''
#include "cubeb_resampler.h"
#include "cubeb_log.h"
#include <cassert>
#include <cmath>
#include <cstdint>
#include <initializer_list>
extern "C" cubeb_log_level cubeb_log_get_level(){return CUBEB_LOG_DISABLED;}
extern "C" cubeb_log_callback cubeb_log_get_callback(){return nullptr;}
extern "C" void cubeb_log_internal(const char*,uint32_t,const char*,...){assert(false);}
extern "C" void cubeb_async_log(const char*,...){assert(false);}
struct State {unsigned channels;bool integer;long remaining=0;};
long data(cubeb_stream*,void* opaque,const void* input,void* output,long wanted){
 assert(!input);auto& s=*static_cast<State*>(opaque);long count=s.remaining<wanted?s.remaining:wanted;
 for(long i=0;i<count*s.channels;++i){if(s.integer)static_cast<int16_t*>(output)[i]=8192;else static_cast<float*>(output)[i]=0.25f;}
 s.remaining-=count;return count;
}
int main(){
 for(unsigned hz:{8000u,44100u,48000u,96000u,192000u})for(unsigned channels:{1u,2u})for(bool integer:{false,true}){
  State s{channels,integer,long(hz/10)};cubeb_stream_params p{};p.rate=48000;p.channels=channels;
  p.format=integer?CUBEB_SAMPLE_S16LE:CUBEB_SAMPLE_FLOAT32LE;
  auto* r=cubeb_resampler_create(nullptr,nullptr,&p,hz,data,&s,CUBEB_RESAMPLER_QUALITY_DEFAULT,CUBEB_RESAMPLER_RECLOCK_NONE);assert(r);
  alignas(64) unsigned char buffer[256*2*sizeof(float)]{};long total=0;bool ended=false,nonzero=false;
  for(unsigned tick=0;tick<100&&!ended;++tick){long count=cubeb_resampler_fill(r,nullptr,nullptr,buffer,256);assert(count>=0&&count<=256);total+=count;
   for(long i=0;i<count*channels;++i){float value=integer?float(reinterpret_cast<int16_t*>(buffer)[i])/32768:reinterpret_cast<float*>(buffer)[i];assert(std::isfinite(value)&&fabs(value)<0.5);nonzero|=fabs(value)>0.1;}
   ended=count<256;
  }
  assert(ended&&nonzero&&s.remaining==0&&total>=4500&&total<=5300);assert(cubeb_resampler_latency(r)>=0);cubeb_resampler_destroy(r);
 }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            tmp = pathlib.Path(directory)
            (tmp / 'include/mozilla').mkdir(parents=True)
            (tmp / 'include/speex').mkdir()
            (tmp / 'include/mozilla/Assertions.h').write_text('#include <assert.h>\n#define MOZ_RELEASE_ASSERT(expr, ...) assert(expr)\n')
            shutil.copy2(speex / 'speex_resampler.h', tmp / 'include/speex/speex_resampler.h')
            cpp = tmp / 'test.cpp'; cpp.write_text(source)
            flags = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
                     '-I'+str(tmp/'include'), '-I'+str(cubeb), '-I'+str(cubeb.parent/'include')]
            result = subprocess.run(['clang', *flags, '-DOUTSIDE_SPEEX', '-DFLOATING_POINT', '-DEXPORT=',
                                     '-c', str(speex/'resample.c'), '-o', str(tmp/'speex.o')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(['clang++', '-std=c++17', *flags, str(cpp), str(cubeb/'cubeb_resampler.cpp'),
                                     str(cubeb/'cubeb_utils.cpp'), str(tmp/'speex.o'), '-o', str(tmp/'test')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(tmp/'test')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
