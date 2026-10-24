// SPDX-License-Identifier: MIT
// Common, real runtime definitions shared by the XUL link gate and final ELF.
// No module loading, allocator interposition, or fabricated service results.
#include "orbisfox/mesa_binding.h"
#include <unistd.h>

extern "C" {
// Main publishes all validated executable targets before EGL or workers run.
// Unbound calls hit the trap in mesa_gnm_stubs.S, never an invented success.
__attribute__((visibility("hidden")))
void* orbis_mesa_gnm_targets[orbisfox::mesa_gnm_symbol_count]{};

// In the final browser, --wrap=sysconf retains the genuine affinity-aware
// provider. The XUL gate uses the real SDK call, not a configure-only shim.
long orbis_sysconf(int name) { return sysconf(name); }

// Allocation-neutral observer; the native application installs it before EGL.
// The link gate's null observer has no allocator/logging dependencies.
void (*orbis_mesa_dispatch_observer)(void*, size_t, unsigned) = nullptr;
void orbis_mesa_dispatch_checkpoint(void* table, size_t bytes, unsigned phase) {
    if (orbis_mesa_dispatch_observer) orbis_mesa_dispatch_observer(table, bytes, phase);
}
}
