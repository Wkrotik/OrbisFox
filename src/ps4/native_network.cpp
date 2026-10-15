#ifdef ORBISFOX_FULL_GECKO
#include "orbisfox/native_network.h"
#include "orbisfox/module_binding.h"
#include "orbisfox/presenter.h"
#include <orbis/Sysmodule.h>
namespace orbisfox {
bool prepare_native_network() {
    // Linking libSceNet does not load it on firmware. The SDK resolver calls
    // sceNetGetDnsInfo from its DNS worker, so ensure readiness before Necko.
    ModuleBinding module;
    if (!module.open(ps4_module_backend(), "libSceNet", ORBIS_SYSMODULE_INTERNAL_NET)) {
        log("ERROR: native Net module not loaded; Necko must remain offline"); return false;
    }
    int32_t (*initialize)() = nullptr;
    void (*dns)() = nullptr; // Resolved/validated only; never called with guessed ABI.
    if (!module.bind("sceNetInit", initialize) || !module.bind("sceNetGetDnsInfo", dns)) {
        log("ERROR: native Net initialization/resolver symbol unavailable; Necko must remain offline"); return false;
    }
    const int32_t result = initialize();
    // Do not invent an already-initialized success code. Unknown errors are
    // failures until observed/documented; no calls through unresolved imports.
    const bool ready = result == 0;
    log("Native Net module initialization/resolver symbol gate: %s init=0x%x; no DNS/HTTP success assumed",
        ready ? "PASS" : "FAIL", unsigned(result));
    return ready;
}
}
#endif
