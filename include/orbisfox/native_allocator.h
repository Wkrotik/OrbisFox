#pragma once
#include <stdint.h>
#include <stddef.h>
namespace orbisfox {
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
bool probe_native_allocator();
}
