import pathlib
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.deps/gecko-layout/media/libcubeb'

class AudioBackendTest(unittest.TestCase):
    def test_real_output_adapter_lifecycle_with_mock_device_and_resampler(self):
        if not (SOURCE/'src/cubeb.c').exists():
            self.skipTest('pinned Gecko source unavailable')
        source = r'''
#include "cubeb/cubeb.h"
#include "cubeb_resampler.h"
#include "cubeb_log.h"
#include "OrbisAudioBackend.h"
#include <atomic>
#include <cassert>
#include <cmath>
#include <cstring>
#include <unistd.h>
// Logger/profiler are outside this device-adapter test.
extern "C" cubeb_log_level cubeb_log_get_level(){return CUBEB_LOG_DISABLED;}
extern "C" cubeb_log_callback cubeb_log_get_callback(){return nullptr;}
extern "C" void cubeb_log_set(cubeb_log_level level,cubeb_log_callback cb){assert(level==CUBEB_LOG_DISABLED&&!cb);}
extern "C" void cubeb_log_internal(const char*,uint32_t,const char*,...){assert(false);}
struct cubeb_resampler {cubeb_stream* stream;cubeb_data_callback cb;void* user;};
extern "C" cubeb_resampler* cubeb_resampler_create(cubeb_stream* s,cubeb_stream_params* in,cubeb_stream_params* out,unsigned target,cubeb_data_callback cb,void* u,cubeb_resampler_quality,cubeb_resampler_reclock){assert(!in&&out->rate==48000&&target==48000);return new cubeb_resampler{s,cb,u};}
extern "C" long cubeb_resampler_fill(cubeb_resampler* r,void* in,long* count,void* out,long n){assert(!in&&!count);return r->cb(r->stream,r->user,nullptr,out,n);}
extern "C" void cubeb_resampler_destroy(cubeb_resampler* r){delete r;}
extern "C" long cubeb_resampler_latency(cubeb_resampler*){return 0;}
struct State {std::atomic<bool> drained{false},error{false};int callback=0,opens=0,closes=0,writes=0,waits=0;bool pending=false,fail=false,mono=false,integer=false;const int16_t* live=nullptr;int16_t left=0,right=0;};
long data(cubeb_stream*,void* u,const void* in,void* out,long n){auto& s=*static_cast<State*>(u);assert(!in&&n==256);++s.callback;if(s.fail)return -1;
 if(s.integer){auto* p=static_cast<int16_t*>(out);for(long i=0;i<200;++i){p[i*2]=10000;p[i*2+1]=-32000;}}
 else {auto* p=static_cast<float*>(out);for(long i=0;i<200;++i){p[i*(s.mono?1:2)]=0.5f;if(!s.mono)p[i*2+1]=-2.0f;}}
 return 200;
}
void state(cubeb_stream*,void* u,cubeb_state value){auto& s=*static_cast<State*>(u);if(value==CUBEB_STATE_DRAINED)s.drained=true;if(value==CUBEB_STATE_ERROR)s.error=true;}
int main(){
 cubeb* context=nullptr;assert(cubeb_init(&context,"test","orbis")!=CUBEB_OK);
 for(int mode=0;mode<4;++mode){State s;s.mono=mode==1;s.integer=mode==2;s.fail=mode==3;
 orbisfox::set_orbis_audio_backend({&s,
  [](void* u)->int32_t {++static_cast<State*>(u)->opens;return 7;},
  [](void* u,int32_t port,const int16_t* pcm)->int32_t {auto& s=*static_cast<State*>(u);assert(port==7);
   if(!pcm){++s.waits;if(s.pending){assert(s.live[0]==s.left&&s.live[1]==s.right);s.pending=false;}return 0;}
   assert(!s.pending);s.pending=true;s.live=pcm;s.left=pcm[0];s.right=pcm[1];++s.writes;
   if(s.integer)assert(s.left==5000&&s.right==-16000);else assert(s.left==8192&&s.right==(s.mono?8192:-32768));return 0;},
  [](void* u,int32_t p)->int32_t {auto& s=*static_cast<State*>(u);assert(p==7&&!s.pending);++s.closes;return 0;}});
 assert(cubeb_init(&context,"test","orbis")==CUBEB_OK);assert(!strcmp(cubeb_get_backend_id(context),"orbis"));
 uint32_t value=0;assert(cubeb_get_preferred_sample_rate(context,&value)==CUBEB_OK&&value==48000);
 assert(cubeb_get_max_channel_count(context,&value)==CUBEB_OK&&value==2);
 cubeb_stream_params params{};params.rate=48000;params.channels=s.mono?1:2;params.layout=s.mono?CUBEB_LAYOUT_MONO:CUBEB_LAYOUT_STEREO;params.format=s.integer?CUBEB_SAMPLE_S16LE:CUBEB_SAMPLE_FLOAT32LE;
 cubeb_stream* stream=nullptr;assert(cubeb_stream_init(context,&stream,"test",nullptr,nullptr,nullptr,&params,256,data,state,&s)==CUBEB_OK);
 assert(cubeb_stream_set_volume(stream,0.5f)==CUBEB_OK);assert(cubeb_stream_set_volume(stream,NAN)==CUBEB_ERROR_INVALID_PARAMETER);
 assert(cubeb_stream_start(stream)==CUBEB_OK);
 for(unsigned i=0;i<1000&&!s.drained&&!s.error;++i)usleep(1000);assert(s.fail?s.error.load():s.drained.load());
 assert(cubeb_stream_stop(stream)==CUBEB_OK);uint64_t position=0;assert(cubeb_stream_get_position(stream,&position)==CUBEB_OK&&position==(s.fail?0:200));
 assert(cubeb_stream_get_latency(stream,&value)==CUBEB_OK&&value==256);
 cubeb_stream_destroy(stream);assert(s.opens==1&&s.closes==1);assert(s.fail?s.writes==0:s.writes==1);cubeb_destroy(context);
 }
 orbisfox::set_orbis_audio_backend({});
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp=pathlib.Path(directory)/'test.cpp';cpp.write_text(source)
            private=pathlib.Path(directory)/'source';patched=private/'media/libcubeb/src/cubeb.c';patched.parent.mkdir(parents=True)
            shutil.copy2(SOURCE/'src/cubeb.c',patched)
            spec=importlib.util.spec_from_file_location('orbis_audio_patch',ROOT/'scripts/patch-gecko-layout.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            module.register_cubeb_source(private);expected=patched.read_bytes();module.register_cubeb_source(private);self.assertEqual(patched.read_bytes(),expected)
            obj=pathlib.Path(directory)/'cubeb.o';binary=pathlib.Path(directory)/'test'
            assertions=pathlib.Path(directory)/'include/mozilla/Assertions.h';assertions.parent.mkdir(parents=True)
            assertions.write_text('#include <assert.h>\n#define MOZ_RELEASE_ASSERT(expr, ...) assert(expr)\n')
            flags=['-I',str(assertions.parent.parent),'-fsanitize=address,undefined','-fno-omit-frame-pointer','-pthread',
                   '-I',str(SOURCE/'include'),'-I',str(SOURCE/'src'),'-I',str(ROOT/'gecko/orbisfox')]
            result=subprocess.run(['clang','-DUSE_ORBIS',*flags,'-c',str(patched),'-o',str(obj)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',*flags,str(cpp),str(ROOT/'gecko/orbisfox/cubeb_orbis.cpp'),str(SOURCE/'src/cubeb_mixer.cpp'),str(SOURCE/'src/cubeb_utils.cpp'),str(obj),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
