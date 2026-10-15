#ifndef ORBISFOX_AUDIO_BACKEND_H
#define ORBISFOX_AUDIO_BACKEND_H
#include <stdint.h>
namespace orbisfox {
struct OrbisAudioBackend {
 void* user=nullptr;
 int32_t (*open)(void*)=nullptr; // 256frames,48kHz,S16stereo,default main output
 int32_t (*output)(void*,int32_t,const int16_t*)=nullptr;
 int32_t (*close)(void*,int32_t)=nullptr;
};
void set_orbis_audio_backend(const OrbisAudioBackend& backend);
bool orbis_audio_backend_ready();
}
#endif
