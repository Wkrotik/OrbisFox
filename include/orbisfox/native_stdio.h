#pragma once
#include <stdint.h>
namespace orbisfox {
// Full-Gecko only; FILE remains opaque. The native SDK owns its stream locks;
// only the legacy musl SDK needs the external recursive-lock workaround.
bool initialize_native_stdio_locks();
bool probe_native_stdio_locks();
#ifndef ORBISFOX_HOMEBREW_SDK
// Legacy interposer instrumentation, not an available native-libc counter.
uint64_t native_stdio_entry_lock_count();
#endif
}
