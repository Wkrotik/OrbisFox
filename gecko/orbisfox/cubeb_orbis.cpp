#include "OrbisAudioBackend.h"
#include "cubeb/cubeb.h"
#include "cubeb-internal.h"
#include "cubeb_resampler.h"
#include <atomic>
#include <cmath>
#include <cstring>
#include <new>
#include <pthread.h>
namespace {
constexpr unsigned frames=256,rate=48000;
orbisfox::OrbisAudioBackend native{};
}
struct cubeb {const cubeb_ops* ops;orbisfox::OrbisAudioBackend backend;};
struct cubeb_stream {
 cubeb* context=nullptr;void* user_ptr=nullptr;
 cubeb_stream_params requested{};cubeb_state_callback state=nullptr;
 cubeb_resampler* resampler=nullptr;int32_t port=-1;
 pthread_t thread{};pthread_mutex_t control=PTHREAD_MUTEX_INITIALIZER;
 std::atomic<bool> running{false},joinable{false};std::atomic<float> volume{1};
 std::atomic<uint64_t> completedNative{0};
 alignas(64) unsigned char samples[frames*2*sizeof(float)]{};
 alignas(64) int16_t pcm[frames*2]{};
};
namespace orbisfox {
void set_orbis_audio_backend(const OrbisAudioBackend& backend){native=backend;}
bool orbis_audio_backend_ready(){return native.open&&native.output&&native.close;}
}
namespace {
void uncertain(){__builtin_trap();}
struct Lock {pthread_mutex_t* mutex;explicit Lock(pthread_mutex_t* m):mutex(m){if(pthread_mutex_lock(m))uncertain();}~Lock(){if(pthread_mutex_unlock(mutex))uncertain();}};
int16_t sample(cubeb_stream* s,size_t i){
 float value=0;
 if(s->requested.format==CUBEB_SAMPLE_FLOAT32LE)memcpy(&value,s->samples+i*sizeof(float),sizeof(float));
 else {int16_t v=0;memcpy(&v,s->samples+i*sizeof(int16_t),sizeof(v));value=float(v)/32768.0f;}
 value*=s->volume.load(std::memory_order_relaxed);if(!std::isfinite(value))value=0;
 if(value>=1)return INT16_MAX;if(value<=-1)return INT16_MIN;return static_cast<int16_t>(value*32768.0f);
}
void* worker(void* opaque){
 auto* s=static_cast<cubeb_stream*>(opaque);const auto& b=s->context->backend;
 s->state(s,s->user_ptr,CUBEB_STATE_STARTED);uint64_t pending=0;bool ended=false;
 while(s->running.load()){
  // NULL waits for the prior buffer to finish: do not overwrite live PCM.
  if(b.output(b.user,s->port,nullptr)<0){s->state(s,s->user_ptr,CUBEB_STATE_ERROR);ended=true;break;}
  s->completedNative.fetch_add(pending);pending=0;
  const long count=cubeb_resampler_fill(s->resampler,nullptr,nullptr,s->samples,frames);
  if(count<0||count>long(frames)){s->state(s,s->user_ptr,CUBEB_STATE_ERROR);ended=true;break;}
  memset(s->pcm,0,sizeof(s->pcm));
  for(long i=0;i<count;++i){
   s->pcm[i*2]=sample(s,size_t(i)*s->requested.channels);
   s->pcm[i*2+1]=s->requested.channels==2?sample(s,size_t(i)*2+1):s->pcm[i*2];
  }
  if(b.output(b.user,s->port,s->pcm)<0){s->state(s,s->user_ptr,CUBEB_STATE_ERROR);ended=true;break;}
  pending=uint64_t(count);
  if(count<long(frames)){
   if(b.output(b.user,s->port,nullptr)<0)s->state(s,s->user_ptr,CUBEB_STATE_ERROR);
   else {s->completedNative.fetch_add(pending);pending=0;s->state(s,s->user_ptr,CUBEB_STATE_DRAINED);}
   ended=true;break;
  }
 }
 if(pending){
  if(b.output(b.user,s->port,nullptr)<0){if(!ended)s->state(s,s->user_ptr,CUBEB_STATE_ERROR);ended=true;}
  else s->completedNative.fetch_add(pending);
 }
 s->running=false;if(!ended)s->state(s,s->user_ptr,CUBEB_STATE_STOPPED);return nullptr;
}
int stop(cubeb_stream* s){
 if(s->joinable.load()&&pthread_equal(pthread_self(),s->thread))return CUBEB_ERROR;
 Lock lock(&s->control);s->running=false;
 if(s->joinable){if(pthread_join(s->thread,nullptr))uncertain();s->joinable=false;}
 return CUBEB_OK;
}
int start(cubeb_stream* s){
 Lock lock(&s->control);if(s->running)return CUBEB_OK;
 if(s->joinable){if(pthread_equal(pthread_self(),s->thread))return CUBEB_ERROR;if(pthread_join(s->thread,nullptr))uncertain();s->joinable=false;}
 s->running=true;s->joinable=true;
 if(pthread_create(&s->thread,nullptr,worker,s)){s->running=false;s->joinable=false;return CUBEB_ERROR;}
 return CUBEB_OK;
}
void streamDestroy(cubeb_stream* s){
 if(stop(s)!=CUBEB_OK)uncertain();
 if(s->context->backend.close(s->context->backend.user,s->port)!=0)uncertain();
 cubeb_resampler_destroy(s->resampler);if(pthread_mutex_destroy(&s->control))uncertain();delete s;
}
int streamInit(cubeb* c,cubeb_stream** out,const char*,cubeb_devid input,cubeb_stream_params* in,cubeb_devid output,cubeb_stream_params* params,unsigned,cubeb_data_callback callback,cubeb_state_callback state,void* user){
 if(input||in||output||!params||!callback||!state)return CUBEB_ERROR_NOT_SUPPORTED;
 if(params->channels<1||params->channels>2||params->rate<8000||params->rate>192000
    ||(params->format!=CUBEB_SAMPLE_FLOAT32LE&&params->format!=CUBEB_SAMPLE_S16LE))return CUBEB_ERROR_INVALID_FORMAT;
 auto* s=new(std::nothrow) cubeb_stream;if(!s)return CUBEB_ERROR;
 s->context=c;s->user_ptr=user;s->requested=*params;s->state=state;
 s->port=c->backend.open(c->backend.user);if(s->port<0){if(pthread_mutex_destroy(&s->control))uncertain();delete s;return CUBEB_ERROR_DEVICE_UNAVAILABLE;}
 cubeb_stream_params nativeParams=*params;nativeParams.rate=rate;
 s->resampler=cubeb_resampler_create(s,nullptr,&nativeParams,params->rate,callback,user,CUBEB_RESAMPLER_QUALITY_DEFAULT,CUBEB_RESAMPLER_RECLOCK_NONE);
 if(!s->resampler){if(c->backend.close(c->backend.user,s->port)!=0)uncertain();if(pthread_mutex_destroy(&s->control))uncertain();delete s;return CUBEB_ERROR;}
 *out=s;return CUBEB_OK;
}
int maxChannels(cubeb*,uint32_t* value){*value=2;return CUBEB_OK;}
int minLatency(cubeb*,cubeb_stream_params params,uint32_t* value){*value=(frames*params.rate+rate-1)/rate;return CUBEB_OK;}
int preferredRate(cubeb*,uint32_t* value){*value=rate;return CUBEB_OK;}
int position(cubeb_stream* s,uint64_t* value){const long delay=cubeb_resampler_latency(s->resampler);if(delay<0)return CUBEB_ERROR;const uint64_t done=s->completedNative.load();*value=(done>uint64_t(delay)?done-uint64_t(delay):0)*s->requested.rate/rate;return CUBEB_OK;}
int latency(cubeb_stream* s,uint32_t* value){const long delay=cubeb_resampler_latency(s->resampler);if(delay<0)return CUBEB_ERROR;*value=uint32_t(((uint64_t(frames)+uint64_t(delay))*s->requested.rate+rate-1)/rate);return CUBEB_OK;}
int volume(cubeb_stream* s,float value){if(!std::isfinite(value)||value<0||value>1)return CUBEB_ERROR_INVALID_PARAMETER;s->volume=value;return CUBEB_OK;}
const char* id(cubeb*){return "orbis";}
void destroy(cubeb* c){delete c;}
extern "C" int orbis_init(cubeb**,const char*);
constexpr cubeb_ops operations(){cubeb_ops o{};o.init=orbis_init;o.get_backend_id=id;o.get_max_channel_count=maxChannels;o.get_min_latency=minLatency;o.get_preferred_sample_rate=preferredRate;o.destroy=destroy;o.stream_init=streamInit;o.stream_destroy=streamDestroy;o.stream_start=start;o.stream_stop=stop;o.stream_get_position=position;o.stream_get_latency=latency;o.stream_set_volume=volume;return o;}
constexpr cubeb_ops ops=operations();
}
extern "C" int orbis_init(cubeb** out,const char*){
 if(!orbisfox::orbis_audio_backend_ready())return CUBEB_ERROR_DEVICE_UNAVAILABLE;
 auto* c=new(std::nothrow) cubeb{&ops,native};if(!c)return CUBEB_ERROR;*out=c;return CUBEB_OK;
}
