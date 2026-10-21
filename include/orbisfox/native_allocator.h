#pragma once
#include <stdint.h>
#include <stddef.h>
#if defined(ORBISFOX_HOMEBREW_SDK) && (defined(ORBISFOX_SDK_BIN_AUDIT) || defined(ORBISFOX_NATIVE_DIRECT_HEAP) || defined(ORBISFOX_SDK_REALLOC_COMPAT))
#error Native SDK allocator must not use legacy musl wrappers or direct-heap interception
#endif
namespace orbisfox {
#ifndef ORBISFOX_HOMEBREW_SDK
bool initialize_native_allocator_lock();
uint64_t native_allocator_entry_count();
uint64_t native_allocator_realloc_copy_fix_count();
#ifdef ORBISFOX_SDK_BIN_AUDIT
size_t native_allocator_audited_arena_count();
void configure_native_allocator_reclaim(bool verified);
void configure_native_allocator_bin_audit(bool allCalls);
// Mesa requests broader checks only while the existing diagnostics flag is ON.
void configure_native_allocator_mesa_boundary_audit();
// Diagnostic-only observation of genuine Mesa allocations; never owns storage.
void checkpoint_native_mesa_dispatch(void* table, size_t bytes, unsigned phase);
#endif
// Opt-in development diagnostics. Caller retains the trace fd until process
// exit; genuine SDK heap remains owner, and pre-enable objects stay raw.
bool configure_native_allocator_diagnostics(int fd);
bool checkpoint_native_allocator_diagnostics();
#endif
// Actual allocator behavior gate, valid for both SDKs. Native mode neither
// interposes the system heap nor manufactures legacy lock/bin counters.
bool probe_native_allocator();
}
