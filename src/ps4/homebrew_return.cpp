// SPDX-License-Identifier: MIT
// Native SDK main-return boundary only, not a global exit/atexit replacement.
#if defined(ORBISFOX_FULL_GECKO) && defined(ORBISFOX_HOMEBREW_SDK)
#include "orbisfox/ps4_services.h"
#include "orbisfox/presenter.h"
#include <time.h>
#include <orbis/libkernel.h>

namespace {
bool monotonic(timespec& value) {
    return clock_gettime(CLOCK_MONOTONIC, &value) == 0 && value.tv_sec >= 0 &&
           value.tv_nsec >= 0 && value.tv_nsec < 1000000000;
}
}

// The pinned CRT invokes this hook after main's automatic C++ objects have
// unwound. Normal browser shutdown uses the application manager already; this
// also covers startup-error returns, avoiding the console-proven raw exit fault.
// It does NOT claim to execute SDK atexit/global C++ destructor/loader cleanup.
extern "C" [[noreturn]] void catchReturnFromMain(int status) {
    orbisfox::log("Native SDK main returned status=%d; requesting app-manager exit (global atexit cleanup unproven)", status);
    if (orbisfox::request_system_exit() != 0) {
        orbisfox::log("Native SDK main-return exit rejected; refusing raw exit");
        __builtin_trap();
    }
    timespec start{};
    if (!monotonic(start)) __builtin_trap();
    // A successful request can return before the OS terminates the process.
    // Both real elapsed time and a finite iteration bound protect this wait.
    for (unsigned wait = 0; wait < 500; ++wait) {
        timespec now{};
        if (!monotonic(now) || now.tv_sec < start.tv_sec ||
            (now.tv_sec == start.tv_sec && now.tv_nsec < start.tv_nsec)) __builtin_trap();
        const double elapsed = double(now.tv_sec - start.tv_sec) +
                               double(now.tv_nsec - start.tv_nsec) / 1e9;
        if (elapsed >= 5) break;
        if (sceKernelUsleep(10000) != 0) __builtin_trap();
    }
    orbisfox::log("Native SDK main-return app-manager exit timed out; refusing raw exit");
    __builtin_trap();
}
#endif
