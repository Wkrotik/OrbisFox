// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>

// Main publishes once before EGL or workers run. The strict XUL link gate leaves
// this observer null; it must not acquire native application dependencies.
extern "C" {
extern void (*orbis_mesa_dispatch_observer)(void*, size_t, unsigned);
void orbis_mesa_dispatch_checkpoint(void* table, size_t bytes, unsigned phase);
}

namespace orbisfox {
// Internal native startup boundary, never exposed through the web bridge.
// resolve must check the real module export AND executable memory protection.
struct MesaModuleBackend {
    void* user;
    int32_t (*find)(void*);
    int32_t (*load)(void*, const char*, int32_t* entryResult);
    bool (*resolve)(void*, int32_t, const char*, void**);
};
constexpr size_t mesa_gnm_symbol_count = 10;

inline bool bind_mesa_gnm(const MesaModuleBackend& backend, void** targets) {
    if (!targets || !backend.find || !backend.load || !backend.resolve) return false;
    int32_t handle = backend.find(backend.user);
    // -1 alone means a successful enumeration with no matching module.
    // Other negatives are query failures, not permission to load or retry.
    if (handle < -1) return false;
    if (handle == -1) {
        const char* paths[] = {"libSceGnmDriver.sprx", "/common/lib/libSceGnmDriver.sprx",
                               "/system/common/lib/libSceGnmDriver.sprx"};
        for (const char* path : paths) {
            int32_t entry = 0;
            const int32_t result = backend.load(backend.user, path, &entry);
            if (result >= 0) {
                if (entry < 0) return false;
                handle = backend.find(backend.user);
                break;
            }
            // Retry only the actual ENOENT. Never guess a Sysmodule ID, retry
            // permission/entry failures, remap paths or copy firmware files.
            if (uint32_t(result) != UINT32_C(0x80020002)) return false;
        }
    }
    if (handle < 0) return false;
    const char* names[] = {
#define ORBIS_MESA_GNM(index, name) #name,
#include "orbisfox/mesa_gnm_symbols.inc"
#undef ORBIS_MESA_GNM
    };
    static_assert(sizeof(names)/sizeof(names[0]) == mesa_gnm_symbol_count, "GNM binding count");
    void* pending[mesa_gnm_symbol_count]{};
    for (size_t i = 0; i < mesa_gnm_symbol_count; ++i) {
        if (!backend.resolve(backend.user, handle, names[i], &pending[i]) || !pending[i]) return false;
    }
    // Startup is main-thread-only, before Mesa or its workers can run. A failed
    // lookup never partially updates the table or replaces working bindings.
    for (size_t i = 0; i < mesa_gnm_symbol_count; ++i) targets[i] = pending[i];
    return true;
}

bool prepare_native_mesa();
} // namespace orbisfox
