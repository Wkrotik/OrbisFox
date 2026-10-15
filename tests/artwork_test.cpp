#include "orbisfox/artwork.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <vector>
using namespace orbisfox;
static void save(const std::vector<uint8_t>& bytes) {
    FILE* f = fopen("build/artwork-test.rgba", "wb"); assert(f);
    assert(fwrite(bytes.data(), 1, bytes.size(), f) == bytes.size()); fclose(f);
}
int main() {
    const uint8_t header[] = {'O','R','B','F','I','M','G','1',2,0,0,0,2,0,0,0};
    const uint8_t pixels[] = {255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,255,255};
    std::vector<uint8_t> image(header, header + 16); image.insert(image.end(), pixels, pixels + 16);
    uint8_t bytes[64]; memset(bytes, 0xA5, sizeof(bytes));
    Surface surface{bytes + 16, 2, 2, 16};
    save(image); assert(load_artwork("build/artwork-test.rgba", surface));
    assert(memcmp(surface.pixels, pixels, 8) == 0);
    assert(memcmp(surface.pixels + 16, pixels + 8, 8) == 0);
    for (size_t i = 0; i < sizeof(bytes); ++i)
        if (i < 16 || (i >= 24 && i < 32) || i >= 40) assert(bytes[i] == 0xA5);
    assert(!load_artwork(nullptr, surface));
    assert(!load_artwork("build/no-such-image.rgba", surface));
    image[0] = 'X'; save(image); assert(!load_artwork("build/artwork-test.rgba", surface));
    image[0] = 'O'; image[8] = 3; save(image); assert(!load_artwork("build/artwork-test.rgba", surface));
    image[8] = 2; image.push_back(0); save(image); assert(!load_artwork("build/artwork-test.rgba", surface));
    image.resize(20); save(image); assert(!load_artwork("build/artwork-test.rgba", surface));
    image.resize(8); save(image); assert(!load_artwork("build/artwork-test.rgba", surface));
    remove("build/artwork-test.rgba");
    puts("artwork: pixel order, stride, guards, missing file, malformed header, truncation and trailing data passed");
}
