#ifndef ORBISFOX_EXECUTABLE_MEMORY_H
#define ORBISFOX_EXECUTABLE_MEMORY_H
#include <stddef.h>
#include <stdint.h>
namespace orbisfox {
constexpr size_t jitArenaBytes=64*1024*1024,jitNativePage=16384;
struct OrbisJitBackend {
 void* user=nullptr;
 int32_t (*create)(void*,size_t,int*)=nullptr;
 int32_t (*map)(void*,int,void**)=nullptr;
 int32_t (*protect)(void*,void*,size_t,int)=nullptr;
 bool (*query)(void*,void*,size_t,int)=nullptr;
 int32_t (*unmap)(void*,void*,size_t)=nullptr;
 int32_t (*close)(void*,int)=nullptr;
};
struct OrbisJitStats {bool ready=false,claimed=false;uint32_t failedPhase=0;int32_t lastResult=0;size_t reservedBytes=0,committedBytes=0;};
// Prepare before JS_Init. Failure is an honest interpreter fallback; no RWX
// mapping request. Only compiler-owned shared-code memory uses this backend.
bool prepare_orbis_executable_memory(const OrbisJitBackend& backend);
void* reserve_orbis_executable_memory(size_t bytes);
void release_orbis_executable_memory(void* address,size_t bytes);
bool protect_orbis_executable_memory(void* address,size_t bytes,int protection);
void shutdown_orbis_executable_memory();
OrbisJitStats orbis_jit_memory_stats();
// After an evidence-only trial released its arena, restore the outcome that
// decided the backend (the shared-code gate) so reports describe it. Ignored
// while an arena exists; never marks the backend ready.
void record_orbis_jit_gate_outcome(const OrbisJitStats& outcome);
const char* orbis_jit_gate_reason(const OrbisJitStats& state);
}
#endif
