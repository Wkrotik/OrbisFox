// SPDX-License-Identifier: MIT
#include "orbisfox/mesa_binding.h"
#include "orbisfox/mesa_threading.h"
#include "orbisfox/module_binding.h"
#include "orbisfox/native_allocator.h"
#include "orbisfox/presenter.h"
#include <orbis/libkernel.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

// Written on main before XRE/worker creation, immutable while workers run.
static bool bindings_ready = false;
static bool attempted = false;

// Only compiled/linked for the explicit experimental native Mesa build.
extern "C" {
bool orbis_mesa_native_ready() { return bindings_ready; }
// Defined once in the common bridge used by both the XUL gate and final ELF.
extern __attribute__((visibility("hidden"))) void* orbis_mesa_gnm_targets[orbisfox::mesa_gnm_symbol_count];
}

namespace orbisfox {
static int32_t find_gnm(void*) {
    OrbisKernelModule modules[256]{};
    size_t count = 0;
    const int32_t result = sceKernelGetModuleList(modules, sizeof(modules)/sizeof(modules[0]), &count);
    if (result < 0 || count > sizeof(modules)/sizeof(modules[0])) {
        log("Experimental Mesa: module enumeration failed rc=0x%x count=%zu", result, count);
        return -2; // Query failure, distinct from a genuine no-match.
    }
    for (size_t i = 0; i < count; ++i) {
        OrbisKernelModuleInfo info{};
        info.size = sizeof(info);
        if (sceKernelGetModuleInfo(modules[i], &info) < 0 || !memchr(info.name, 0, sizeof(info.name))) continue;
        const char* slash = strrchr(info.name, '/');
        const char* name = slash ? slash+1 : info.name;
        if (!strcmp(name, "libSceGnmDriver") || !strcmp(name, "libSceGnmDriver.sprx") ||
            !strcmp(name, "libSceGnmDriver.prx") || !strcmp(name, "libSceGnmDriver.so")) {
            if (modules[i] <= INT32_MAX) return int32_t(modules[i]);
            return -2;
        }
    }
    return -1;
}
static int32_t load_gnm(void*, const char* path, int32_t* entry) {
    const int32_t result = sceKernelLoadStartModule(path, 0, nullptr, 0, nullptr, entry);
    log("Experimental Mesa: GNM load %s rc=0x%x entry=0x%x", path, result, *entry);
    return result;
}
static bool resolve_gnm(void*, int32_t handle, const char* name, void** address) {
    const ModuleBackend backend = ps4_module_backend();
    return backend.resolve && backend.resolve(backend.user, handle, name, address);
}
bool prepare_native_mesa() {
    // Binding is separate from the subsequent owned GLES shader/pixel gate.
    // Do not retry either operation after Gecko workers have started.
    if (attempted) return bindings_ready;
    attempted = true;
    // Configure before the startup shader gate creates/caches any GL context.
    // Keep real GPU rendering, but do not add an unvalidated GL marshalling
    // worker to Gecko's own render thread. This is a stability candidate, not
    // proof that the optional worker caused the observed memory corruption.
    if (!configure_mesa_render_thread_policy(setenv, getenv)) {
        log("Experimental Mesa: GL dispatch policy setup failed; native GPU unavailable");
        return false;
    }
    log("Experimental Mesa: direct GL dispatch on owning thread; GPU rendering retained");
#ifdef ORBISFOX_SDK_BIN_AUDIT
    configure_native_allocator_mesa_boundary_audit();
    orbis_mesa_dispatch_observer = checkpoint_native_mesa_dispatch;
#endif
    bindings_ready = bind_mesa_gnm({nullptr, find_gnm, load_gnm, resolve_gnm}, orbis_mesa_gnm_targets);
    log("Experimental Mesa: checked GNM bindings %s", bindings_ready ? "ready" : "unavailable");
    return bindings_ready;
}
} // namespace orbisfox
