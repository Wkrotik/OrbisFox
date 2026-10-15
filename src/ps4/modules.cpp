#include "orbisfox/module_binding.h"
#include "orbisfox/presenter.h"
#include <stdio.h>
#include <string.h>
#include <orbis/libkernel.h>
#include <orbis/Sysmodule.h>

namespace orbisfox {
static bool module_name_matches(const char* reported, const char* requested) {
    const char* slash = strrchr(reported, '/');
    const char* basename = slash ? slash + 1 : reported;
    if (strcmp(basename, requested) == 0) return true;
    size_t size = strlen(requested);
    if (strncmp(basename, requested, size) != 0) return false;
    const char* suffix = basename + size;
    return strcmp(suffix, ".sprx") == 0 || strcmp(suffix, ".prx") == 0 || strcmp(suffix, ".so") == 0;
}
static bool load_service(void*, const char* name, uint32_t id, int32_t* handle) {
    *handle = -1;
    const bool internal = (id & UINT32_C(0x80000000)) != 0;
    log("Service module %s: load %s id=0x%x begin", name, internal ? "internal" : "public", id);
    int32_t rc = internal ? (int32_t)sceSysmoduleLoadModuleInternal(static_cast<OrbisSysModuleInternal>(id)) :
                           (int32_t)sceSysmoduleLoadModule(static_cast<OrbisSysModule>(id));
    log("Service module %s: load rc=0x%x", name, rc);
    if (rc < 0) return false;
    // This API's capacity is a count of module handles, not a byte size.
    OrbisKernelModule modules[256]{};
    size_t count = 0;
    log("Service module %s: enumerate module handles begin", name);
    rc = sceKernelGetModuleList(modules, sizeof(modules) / sizeof(modules[0]), &count);
    log("Service module %s: module list rc=0x%x count=%zu", name, rc, count);
    if (rc < 0 || count > sizeof(modules) / sizeof(modules[0])) return false;
    for (size_t i = 0; i < count; ++i) {
        OrbisKernelModuleInfo info{};
        info.size = sizeof(info);
        rc = sceKernelGetModuleInfo(modules[i], &info);
        if (rc < 0 || !memchr(info.name, 0, sizeof(info.name))) continue;
        if (module_name_matches(info.name, name)) {
            *handle = (int32_t)modules[i];
            log("Service module %s: handle=%d name=%s", name, *handle, info.name);
            return *handle >= 0;
        }
    }
    log("Service module %s: no matching handle; refusing service calls", name);
    // Bounded diagnostics if a future firmware uses different module names.
    for (size_t i = 0; i < count; ++i) {
        OrbisKernelModuleInfo info{};
        info.size = sizeof(info);
        rc = sceKernelGetModuleInfo(modules[i], &info);
        if (rc == 0) log("Loaded module: handle=%u name=%.255s", modules[i], info.name);
    }
    return false;
}
static bool resolve_service(void*, int32_t handle, const char* name, void** address) {
    *address = nullptr;
    log("Service symbol %s: dlsym handle=%d begin", name, handle);
    int32_t rc = sceKernelDlsym(handle, name, address);
    log("Service symbol %s: dlsym rc=0x%x address=%p", name, rc, *address);
    if (rc < 0 || !*address) return false;
    void* low = nullptr;
    void* high = nullptr;
    int32_t protection = 0;
    rc = sceKernelQueryMemoryProtection(*address, &low, &high, &protection);
    uintptr_t target = reinterpret_cast<uintptr_t>(*address);
    if (rc < 0 || !(protection & ORBIS_KERNEL_PROT_CPU_EXEC)
        || target < reinterpret_cast<uintptr_t>(low) || target >= reinterpret_cast<uintptr_t>(high)) {
        log("Service symbol %s: non-executable/unverified address query=0x%x prot=0x%x", name, rc, protection);
        *address = nullptr;
        return false;
    }
    return true;
}
ModuleBackend ps4_module_backend() { return {nullptr, load_service, resolve_service}; }
} // namespace orbisfox
