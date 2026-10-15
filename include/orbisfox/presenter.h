#pragma once
#include "orbisfox/surface.h"
namespace orbisfox {
// Owns presentation resources, not layout or web content. Present is synchronous
// so the caller can reuse the RGBA source immediately after it returns.
class Presenter {
public:
    virtual ~Presenter() = default;
    virtual bool init(int width, int height) = 0;
    virtual bool present(const Surface& surface) = 0;
    // Explicit cleanup while diagnostic logging is still open.
    virtual void stop() = 0;
    virtual const char* name() const = 0;
    virtual const char* details() const = 0;
};
Presenter& piglet_presenter();
Presenter& videoout_presenter();
void log(const char* format, ...);
void close_log();
Diagnostics run_platform_probes(bool videoout_only = false);
} // namespace orbisfox
