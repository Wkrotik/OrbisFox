#pragma once
#include "orbisfox/surface.h"
#include <stddef.h>
#include <stdint.h>
namespace orbisfox {
// Real SpiderMonkey interpreter + narrow native drawing bridge, not a DOM or
// HTML/CSS renderer. The bundled script is trusted; no network/file APIs exposed.
// One active canvas per process; all methods/destruction run on its owner thread.
class JsCanvas {
public:
    using Logger = void (*)(const char*);
    JsCanvas() = default;
    ~JsCanvas();
    JsCanvas(const JsCanvas&) = delete;
    JsCanvas& operator=(const JsCanvas&) = delete;
    bool init(Logger logger = nullptr);
    bool evaluate_integer(const char* source, size_t length, int& result, unsigned timeout_ms = 200);
    bool load_demo(const char* path);
    bool render(Surface& surface, int cursor_x, int cursor_y, bool click, double elapsed_ms);
    void stop();
    const char* error() const;
    uint32_t commands() const;
    unsigned self_tests() const;
private:
    struct State;
    State* state_ = nullptr;
    char error_[192] = "JAVASCRIPT NOT STARTED";
};
// Call only after all JsCanvas instances are stopped; JS_Init cannot follow this.
void shutdown_javascript_runtime();
}
