#pragma once
#include "orbisfox/module_binding.h"
#include <orbis/Pad.h>
#include <orbis/UserService.h>

namespace orbisfox {
bool hide_splash_screen();
// On success the application is terminated by the PS4 application manager.
// If the request returns, keep the app alive instead of falling back to _exit.
int32_t request_system_exit();
class Controller {
    ModuleBinding user_module, pad_module;
    decltype(&::sceUserServiceInitialize) user_initialize = nullptr;
    decltype(&::sceUserServiceGetInitialUser) get_initial_user = nullptr;
    decltype(&::scePadInit) pad_init = nullptr;
    decltype(&::scePadOpen) pad_open = nullptr;
    decltype(&::scePadReadState) pad_read = nullptr;
    decltype(&::scePadClose) pad_close = nullptr;
    uint16_t touch_width = 1920, touch_height = 943;
    int32_t handle = -1, last_read_error = 0;
    bool first_poll = true;
public:
    ~Controller() { stop(); }
    bool init();
    bool poll(OrbisPadData& data);
    bool available() const { return handle >= 0; }
    uint16_t touch_resolution_x() const { return touch_width; }
    uint16_t touch_resolution_y() const { return touch_height; }
    void stop();
};
} // namespace orbisfox
