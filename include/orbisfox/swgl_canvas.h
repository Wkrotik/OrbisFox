#pragma once
#include "orbisfox/surface.h"
namespace orbisfox {
// Actual Firefox SWGL runtime, with generated WebRender shaders. This adapter
// establishes the CPU framebuffer boundary; it is not Gecko HTML/CSS layout.
class SwglCanvas {
    void* context = nullptr;
    uint8_t* bgra = nullptr;
    int width = 0, height = 0, transform = -1;
    uint32_t program = 0, vbo = 0, vao = 0;
public:
    SwglCanvas() = default;
    SwglCanvas(const SwglCanvas&) = delete;
    SwglCanvas& operator=(const SwglCanvas&) = delete;
    ~SwglCanvas() { stop(); }
    bool init(int width, int height);
    bool render_shader_test(Surface destination);
    void stop();
};
} // namespace orbisfox
