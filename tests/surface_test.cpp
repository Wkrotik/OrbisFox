#include "orbisfox/surface.h"
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <vector>
using namespace orbisfox;
int main() {
    uint8_t storage[64]; memset(storage, 0x55, sizeof(storage));
    Surface s{storage + 8, 3, 2, 16};
    assert(valid(s));
    fill_rect(s, -1, -1, 3, 3, {1,2,3,255});
    for (int y = 0; y < 2; ++y) {
        for (int x = 0; x < 2; ++x) {
            const uint8_t* p = s.pixels + y * s.stride + x * 4;
            assert(p[0] == 1 && p[1] == 2 && p[2] == 3 && p[3] == 255);
        }
        assert(s.pixels[y * s.stride + 8] == 0x55);
        assert(s.pixels[y * s.stride + 12] == 0x55); // row padding
    }
    assert(storage[7] == 0x55 && storage[40] == 0x55);
    uint8_t before[64]; memcpy(before, storage, sizeof(storage));
    fill_rect(s, INT_MAX, INT_MAX, INT_MAX, INT_MAX, {0,0,0,0});
    fill_rect(s, INT_MIN, INT_MIN, INT_MAX, INT_MAX, {0,0,0,0});
    fill_rect(s, 0, 0, -1, 5, {0,0,0,0});
    assert(memcmp(before, storage, sizeof(storage)) == 0);
    uint8_t bgra[24];
    rgba_to_bgra(bgra, s);
    assert(bgra[0] == 3 && bgra[1] == 2 && bgra[2] == 1 && bgra[3] == 255);
    assert(!valid({nullptr, 3, 2, 16}));
    assert(!valid({storage, 3, 2, 8}));
    assert(!valid({storage, 3, 2, SIZE_MAX}));
    assert(!valid({storage, 0, 2, 16}));
    text(s, INT_MAX, INT_MAX, "TEXT\nCLIP", 32, {0,0,0,0});
    text(s, -500, -500, "TEXT", 1, {0,0,0,0});
    assert(memcmp(before, storage, sizeof(storage)) == 0);

    // Full UI smoke test under ASan/UBSan; produce a preview for inspection.
    std::vector<uint8_t> pixels(1280 * 720 * 4);
    Surface ui{pixels.data(), 1280, 720, 1280 * 4};
    Diagnostics d{"HOST PREVIEW", "CREATE / JOIN OK", "PERMISSION CHANGE OK",
                  "DEVICE READ OK", "WRITABLE LOG", "EGL 1.4\nGL: OPENGL ES 2.0\nGPU: HOST PREVIEW"};
    draw_probe(ui, d, 1, 900, 580);
    assert(pixels[0] == 31 && pixels[3] == 255);
    const size_t red = (380 * 1280 + 50) * 4;
    assert(pixels[red] == 255 && pixels[red + 1] == 0 && pixels[red + 2] == 0);
    FILE* preview = fopen("build/probe-preview.ppm", "wb");
    assert(preview);
    fprintf(preview, "P6\n1280 720\n255\n");
    for (size_t i = 0; i < pixels.size(); i += 4) assert(fwrite(pixels.data() + i, 1, 3, preview) == 3);
    fclose(preview);
    draw_probe(ui, d, 0, 10, 10);
    // Also ensure the UI clips safely when the surface is smaller than designed.
    draw_probe(s, d, 0, INT_MAX, INT_MAX);
    puts("surface: clipping, stride, RGBA/BGRA, text and UI tests passed");
}
