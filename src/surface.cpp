#include "orbisfox/surface.h"
#include <limits.h>
#if defined(__SSE2__)
#include <emmintrin.h>
#endif

namespace orbisfox {
bool valid(const Surface& s) {
    return s.pixels && s.width > 0 && s.height > 0
        && (size_t)s.width <= SIZE_MAX / 4
        && s.stride >= (size_t)s.width * 4
        && (size_t)s.height <= SIZE_MAX / s.stride;
}
void fill_rect(Surface s, int x, int y, int w, int h, Color c) {
    if (!valid(s) || w <= 0 || h <= 0) return;
    int64_t right = (int64_t)x + w, bottom = (int64_t)y + h;
    int x0 = x < 0 ? 0 : x, y0 = y < 0 ? 0 : y;
    int x1 = right > s.width ? s.width : (int)right;
    int y1 = bottom > s.height ? s.height : (int)bottom;
    for (int py = y0; py < y1; ++py) {
        for (int px = x0; px < x1; ++px) {
            uint8_t* p = s.pixels + (size_t)py * s.stride + (size_t)px * 4;
            p[0] = c.r; p[1] = c.g; p[2] = c.b; p[3] = c.a;
        }
    }
}
// Original minimal 5x7 bitmap alphabet for diagnostic labels, not web fonts.
static const uint8_t glyphs[][7] = {
    {14,17,17,31,17,17,17}, {30,17,17,30,17,17,30},
    {14,17,16,16,16,17,14}, {30,17,17,17,17,17,30},
    {31,16,16,30,16,16,31}, {31,16,16,30,16,16,16},
    {14,17,16,23,17,17,15}, {17,17,17,31,17,17,17},
    {14,4,4,4,4,4,14}, {7,2,2,2,18,18,12},
    {17,18,20,24,20,18,17}, {16,16,16,16,16,16,31},
    {17,27,21,21,17,17,17}, {17,25,21,19,17,17,17},
    {14,17,17,17,17,17,14}, {30,17,17,30,16,16,16},
    {14,17,17,17,21,18,13}, {30,17,17,30,20,18,17},
    {15,16,16,14,1,1,30}, {31,4,4,4,4,4,4},
    {17,17,17,17,17,17,14}, {17,17,17,17,17,10,4},
    {17,17,17,21,21,21,10}, {17,17,10,4,10,17,17},
    {17,17,10,4,4,4,4}, {31,1,2,4,8,16,31},
    {14,17,19,21,25,17,14}, {4,12,4,4,4,4,14},
    {14,17,1,2,4,8,31}, {30,1,1,14,1,1,30},
    {2,6,10,18,31,2,2}, {31,16,16,30,1,1,30},
    {14,16,16,30,17,17,14}, {31,1,2,4,8,8,8},
    {14,17,17,14,17,17,14}, {14,17,17,15,1,1,14},
    {0,0,4,0,4,0,0}, {0,0,0,31,0,0,0}, // : -
    {0,0,0,0,0,4,0}, {1,2,2,4,8,8,16}, // . /
    {14,17,1,2,4,0,4} // ?
};
void text(Surface s, int x, int y, const char* value, int scale, Color c) {
    if (!value || !valid(s) || scale < 1 || scale > 32) return;
    int64_t cx = x, cy = y;
    for (const unsigned char* ch = (const unsigned char*)value; *ch; ++ch) {
        if (*ch == '\n') { cx = x; cy += 9 * scale; continue; }
        unsigned char k = *ch;
        if (k >= 'a' && k <= 'z') k -= 'a' - 'A';
        int index = k >= 'A' && k <= 'Z' ? k - 'A' :
                    k >= '0' && k <= '9' ? k - '0' + 26 :
                    k == ':' ? 36 : k == '-' ? 37 : k == '.' ? 38 : k == '/' ? 39 : 40;
        if (k != ' ' && cx >= INT_MIN && cx <= INT_MAX - 5 * scale
            && cy >= INT_MIN && cy <= INT_MAX - 7 * scale) {
            for (int row = 0; row < 7; ++row)
                for (int col = 0; col < 5; ++col)
                    if (glyphs[index][row] & (1 << (4 - col)))
                        fill_rect(s, (int)cx + col * scale, (int)cy + row * scale, scale, scale, c);
        }
        cx += 6 * scale;
    }
}
namespace {
void swap_red_blue(uint8_t* out, const uint8_t* in, size_t pixels, bool opaque) {
    size_t x = 0;
#if defined(__SSE2__)
    // SSE2 is mandatory on x86-64; unaligned loads/stores need no extra ISA.
    const __m128i rbMask = _mm_set1_epi32(0x00ff00ff);
    const __m128i gaMask = _mm_set1_epi32(opaque ? 0x0000ff00 : static_cast<int>(0xff00ff00u));
    const __m128i alpha = _mm_set1_epi32(opaque ? static_cast<int>(0xff000000u) : 0);
    for (; pixels - x >= 4; x += 4) {
        const __m128i p = _mm_loadu_si128(reinterpret_cast<const __m128i*>(in + x * 4));
        const __m128i rb = _mm_and_si128(p, rbMask);
        const __m128i swapped = _mm_or_si128(_mm_slli_epi32(rb, 16), _mm_srli_epi32(rb, 16));
        _mm_storeu_si128(reinterpret_cast<__m128i*>(out + x * 4),
            _mm_or_si128(_mm_or_si128(swapped, _mm_and_si128(p, gaMask)), alpha));
    }
#endif
    for (; x < pixels; ++x) {
        const auto* p = in + x * 4; auto* q = out + x * 4;
        const uint8_t r = p[0], g = p[1], b = p[2], a = p[3];
        q[0] = b; q[1] = g; q[2] = r; q[3] = opaque ? 255 : a;
    }
}
}
bool blit_bgra_opaque(Surface target, const uint8_t* source, uint32_t width,
                       uint32_t height, uint32_t stride) {
    if (!valid(target) || !source || !width || !height || width > uint32_t(target.width)
        || height > uint32_t(target.height) || size_t(stride) < size_t(width) * 4
        || size_t(height) > SIZE_MAX / stride) return false;
    for (uint32_t y = 0; y < height; ++y)
        swap_red_blue(target.pixels + size_t(y) * target.stride,
                      source + size_t(y) * stride, width, true);
    return true;
}
void rgba_to_bgra(uint8_t* dst, const Surface& s) {
    if (!dst || !valid(s)) return;
    for (int y = 0; y < s.height; ++y)
        swap_red_blue(dst + size_t(y) * s.width * 4, s.pixels + size_t(y) * s.stride, s.width, false);
}
} // namespace orbisfox
