#include "orbisfox/ps4_services.h"
#include "orbisfox/presenter.h"
#include <string.h>
#include <orbis/libkernel.h>
#include <orbis/SystemService.h>
#include <orbis/Sysmodule.h>
#include <orbis/_types/errors.h>

namespace orbisfox {
bool hide_splash_screen() {
    ModuleBinding module;
    decltype(&::sceSystemServiceHideSplashScreen) hide = nullptr;
    if (!module.open(ps4_module_backend(), "libSceSystemService", ORBIS_SYSMODULE_INTERNAL_SYSTEM_SERVICE)
        || !module.bind("sceSystemServiceHideSplashScreen", hide)) {
        log("SystemService unavailable: skipping hide-splash call");
        return false;
    }
    log("SystemService: resolved hide splash begin");
    int32_t rc = hide();
    log("SystemService: hide splash rc=0x%x", rc);
    return rc == 0;
}
int32_t request_system_exit() {
    ModuleBinding module;
    decltype(&::sceSystemServiceLoadExec) load_exec = nullptr;
    if (!module.open(ps4_module_backend(), "libSceSystemService", ORBIS_SYSMODULE_INTERNAL_SYSTEM_SERVICE)
        || !module.bind("sceSystemServiceLoadExec", load_exec)) {
        log("Exit: SystemService unavailable; refusing a raw process exit");
        return -1;
    }
    // The application manager owns process termination and detaches scanout
    // before reclaiming resources. Returning from main/_exit bypasses that
    // protocol; freeing a currently displayed framebuffer first is unsafe.
    log("Exit: sceSystemServiceLoadExec(exit) begin - app-manager shutdown");
    int32_t rc = load_exec("exit", nullptr);
    log("Exit: unexpected return rc=0x%x; application kept alive", rc);
    return rc;
}
bool Controller::init() {
    stop();
    if (!user_module.open(ps4_module_backend(), "libSceUserService", ORBIS_SYSMODULE_INTERNAL_USER_SERVICE)
        || !user_module.bind("sceUserServiceInitialize", user_initialize)
        || !user_module.bind("sceUserServiceGetInitialUser", get_initial_user)) {
        log("Controller: UserService unavailable; input disabled");
        return false;
    }
    OrbisUserServiceInitializeParams params{};
    params.priority = ORBIS_KERNEL_PRIO_FIFO_LOWEST;
    log("Controller: resolved UserService initialize begin");
    int32_t rc = user_initialize(&params);
    log("Controller: UserService initialize rc=0x%x", rc);
    if (rc != 0 && (uint32_t)rc != ORBIS_USER_SERVICE_ERROR_ALREADY_INITIALIZED) return false;
    int32_t user = -1;
    log("Controller: resolved get initial user begin");
    rc = get_initial_user(&user);
    log("Controller: initial user rc=0x%x user=%d", rc, user);
    if (rc != 0) return false;
    if (!pad_module.open(ps4_module_backend(), "libScePad", ORBIS_SYSMODULE_INTERNAL_PAD)
        || !pad_module.bind("scePadInit", pad_init)
        || !pad_module.bind("scePadOpen", pad_open)
        || !pad_module.bind("scePadReadState", pad_read)
        || !pad_module.bind("scePadClose", pad_close)) {
        log("Controller: Pad module unavailable; input disabled");
        return false;
    }
    log("Controller: resolved scePadInit begin");
    rc = pad_init();
    log("Controller: scePadInit rc=0x%x", rc);
    if (rc != 0) return false;
    log("Controller: resolved scePadOpen begin");
    handle = pad_open(user, 0, 0, nullptr);
    log("Controller: scePadOpen handle=%d", handle);
    last_read_error = 0; first_poll = true;
    touch_width = 1920; touch_height = 943;
    decltype(&::scePadGetControllerInformation) information = nullptr;
    if (handle >= 0 && pad_module.bind("scePadGetControllerInformation", information)) {
        OrbisPadInformation info{};
        int32_t status = information(handle, &info);
        log("Controller: information rc=0x%x touch=%ux%u", status, info.touchResolutionX, info.touchResolutionY);
        if (status == 0 && info.touchResolutionX >= 2 && info.touchResolutionY >= 2) {
            touch_width = info.touchResolutionX; touch_height = info.touchResolutionY;
        }
    }
    log("Controller: touchpad cursor resolution=%ux%u", touch_width, touch_height);
    return handle >= 0;
}
bool Controller::poll(OrbisPadData& data) {
    memset(&data, 0, sizeof(data));
    if (handle < 0 || !pad_read) return false;
    if (first_poll) log("Controller: resolved first scePadReadState begin");
    int32_t rc = pad_read(handle, &data);
    if (first_poll) log("Controller: first read rc=0x%x connected=%u", rc, data.connected);
    first_poll = false;
    if (rc != 0 && rc != last_read_error) log("Controller: read state rc=0x%x", rc);
    last_read_error = rc;
    return rc == 0 && data.connected;
}
void Controller::stop() {
    if (handle >= 0 && pad_close) {
        log("Controller: resolved scePadClose begin");
        int32_t rc = pad_close(handle);
        log("Controller: scePadClose rc=0x%x", rc);
    }
    handle = -1;
}
} // namespace orbisfox
