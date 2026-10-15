#pragma once
#include <stdint.h>

namespace orbisfox {
// Portable guard around platform-specific module loading and symbol lookup.
// The backend logs details; callers must gate all API calls on full binding.
struct ModuleBackend {
    void* user;
    bool (*load)(void* user, const char* name, uint32_t id, int32_t* handle);
    bool (*resolve)(void* user, int32_t handle, const char* symbol, void** address);
};
class ModuleBinding {
    ModuleBackend backend{};
    int32_t handle = -1;
public:
    bool open(ModuleBackend loader, const char* name, uint32_t id) {
        backend = loader; handle = -1;
        if (!backend.load || !backend.resolve || !name || !*name) return false;
        int32_t loaded = -1;
        if (!backend.load(backend.user, name, id, &loaded) || loaded < 0) return false;
        handle = loaded;
        return true;
    }
    template<class Function> bool bind(const char* name, Function& function) {
        function = nullptr;
        if (handle < 0 || !name || !*name || !backend.resolve) return false;
        void* address = nullptr;
        if (!backend.resolve(backend.user, handle, name, &address) || !address) return false;
        function = reinterpret_cast<Function>(address);
        return true;
    }
};
// Implemented by the PS4 backend. System modules remain resident for app lifetime;
// they may be shared with firmware services and are not unloaded by this guard.
ModuleBackend ps4_module_backend();
} // namespace orbisfox
