#include "orbisfox/artwork.h"
#include <stdio.h>
#include <string.h>
namespace orbisfox {
static uint32_t little32(const uint8_t* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
bool load_artwork(const char* path, Surface dst) {
    if (!path || !valid(dst)) return false;
    FILE* file = fopen(path, "rb");
    if (!file) return false;
    uint8_t header[16];
    bool ok = fread(header, 1, sizeof(header), file) == sizeof(header)
        && memcmp(header, "ORBFIMG1", 8) == 0
        && little32(header + 8) == uint32_t(dst.width)
        && little32(header + 12) == uint32_t(dst.height);
    if (ok) {
        const size_t row = size_t(dst.width) * 4;
        for (int y = 0; y < dst.height; ++y) {
            if (fread(dst.pixels + size_t(y) * dst.stride, 1, row, file) != row) {
                ok = false;
                break;
            }
        }
        if (ok) ok = fgetc(file) == EOF && !ferror(file);
    }
    fclose(file);
    return ok;
}
}
