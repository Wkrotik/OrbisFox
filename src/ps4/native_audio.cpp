#include "orbisfox/native_audio.h"
#include "orbisfox/module_binding.h"
#include "../../gecko/orbisfox/OrbisAudioBackend.h"
#include <orbis/AudioOut.h>
#include <orbis/Sysmodule.h>
#include <stdio.h>
namespace orbisfox {
namespace {
ModuleBinding module;
struct Functions {
 decltype(&::sceAudioOutInit) init=nullptr;
 decltype(&::sceAudioOutOpen) open=nullptr;
 decltype(&::sceAudioOutOutput) output=nullptr;
 decltype(&::sceAudioOutClose) close=nullptr;
} functions;
}
bool prepare_native_audio(){
 set_orbis_audio_backend({});
 if(!module.open(ps4_module_backend(),"libSceAudioOut",ORBIS_SYSMODULE_INTERNAL_AUDIOOUT)
    || !module.bind("sceAudioOutInit",functions.init)
    || !module.bind("sceAudioOutOpen",functions.open)
    || !module.bind("sceAudioOutOutput",functions.output)
    || !module.bind("sceAudioOutClose",functions.close))return false;
 const int32_t initialized=functions.init();
 if(initialized){printf("AudioOut init failed rc=0x%x\n",unsigned(initialized));return false;}
 OrbisAudioBackend backend{&functions,
  [](void* user)->int32_t {auto& f=*static_cast<Functions*>(user);return f.open(ORBIS_USER_SERVICE_USER_ID_SYSTEM,ORBIS_AUDIO_OUT_PORT_TYPE_MAIN,0,256,48000,ORBIS_AUDIO_OUT_PARAM_FORMAT_S16_STEREO);},
  [](void* user,int32_t port,const int16_t* pcm)->int32_t {return static_cast<Functions*>(user)->output(port,pcm);},
  [](void* user,int32_t port)->int32_t {return static_cast<Functions*>(user)->close(port);}};
 // Real default endpoint probe, silence only. NULL waits for completion per
 // the pinned public SDK sample; no borrowed buffer survives this function.
 const int32_t port=backend.open(backend.user);
 if(port<0){printf("AudioOut default open failed rc=0x%x\n",unsigned(port));return false;}
 alignas(64) int16_t silence[256*2]{};
 const int32_t sent=backend.output(backend.user,port,silence);
 const int32_t waited=sent<0?sent:backend.output(backend.user,port,nullptr);
 if(backend.close(backend.user,port)!=0)__builtin_trap();
 if(sent<0||waited<0){printf("AudioOut default silence probe failed send=0x%x wait=0x%x\n",unsigned(sent),unsigned(waited));return false;}
 set_orbis_audio_backend(backend);return true;
}
}
