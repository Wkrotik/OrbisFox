#pragma once
#include <stddef.h>
#include <stdint.h>

namespace orbisfox {
// Opaque RGBA8, top-left origin, explicit byte stride. A future SWGL adapter
// must convert BGRA/premultiplied output at this boundary, not guess its format.
struct Surface {
    uint8_t* pixels;
    int width;
    int height;
    size_t stride;
};
struct Color { uint8_t r, g, b, a; };
bool valid(const Surface& surface);
void fill_rect(Surface surface, int x, int y, int width, int height, Color color);
void text(Surface surface, int x, int y, const char* value, int scale, Color color);
void rgba_to_bgra(uint8_t* destination, const Surface& source);
// Caller owns readable source rows. No allocation; explicit channel conversion
// preserves the native Gecko host's established opaque scanout semantics.
bool blit_bgra_opaque(Surface target, const uint8_t* source, uint32_t width,
                       uint32_t height, uint32_t stride);
struct Diagnostics {
    const char* renderer;
    const char* threads;
    const char* memory;
    const char* entropy;
    const char* storage;
    const char* graphics;
    const char* controller = "NOT INITIALIZED";
    const char* engine = "FIREFOX SWGL - NOT YET TESTED";
    const char* runtime = "SQUARE: TEST EXPERIMENTAL RUST RUNTIME";
};
void draw_probe(Surface surface, const Diagnostics& diagnostics, int page, int cursor_x, int cursor_y);
} // namespace orbisfox
