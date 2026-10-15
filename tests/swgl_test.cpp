#include "orbisfox/swgl_canvas.h"
#include <assert.h>
#include <stdio.h>
#include <vector>
using namespace orbisfox;
int main() {
    SwglCanvas renderer;
    assert(!renderer.init(0, 64));
    assert(renderer.init(64, 64));
    const size_t stride = 64 * 4 + 16;
    std::vector<uint8_t> bytes(stride * 64 + 32, 0xA5);
    Surface s{bytes.data() + 16, 64, 64, stride};
    assert(renderer.render_shader_test(s));
    auto pixel = [&](int x, int y) { return s.pixels + y * stride + x * 4; };
    assert(pixel(0, 0)[0] == 19 && pixel(0, 0)[1] == 27 && pixel(0, 0)[2] == 47 && pixel(0, 0)[3] == 255);
    const uint8_t* red = pixel(15, 24), *green = pixel(48, 24), *blue = pixel(32, 46);
    assert(red[0] > red[1] && red[0] > red[2]);
    assert(green[1] > green[0] && green[1] > green[2]);
    assert(blue[2] > blue[0] && blue[2] > blue[1]);
    for (int y = 0; y < 64; ++y)
        for (size_t x = 256; x < stride; ++x) assert(s.pixels[y * stride + x] == 0xA5);
    assert(bytes[0] == 0xA5 && bytes.back() == 0xA5);
    Surface wrong = s; wrong.width = 63;
    assert(!renderer.render_shader_test(wrong));
    renderer.stop(); renderer.stop();
    assert(!renderer.render_shader_test(s));
    assert(renderer.init(1280, 720));
    std::vector<uint8_t> large(1280 * 720 * 4);
    Surface screen{large.data(), 1280, 720, 1280 * 4};
    assert(renderer.render_shader_test(screen));
    FILE* output = fopen("build/swgl-preview.ppm", "wb"); assert(output);
    fprintf(output, "P6\n1280 720\n255\n");
    for (size_t i = 0; i < large.size(); i += 4) assert(fwrite(large.data() + i, 1, 3, output) == 3);
    fclose(output);
    puts("Firefox SWGL: real generated shader, RGB channel order, top-left orientation, stride and lifecycle passed");
}
