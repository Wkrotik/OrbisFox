#pragma once
#include <stddef.h>
#include <stdint.h>
namespace orbisfox {
struct TouchPoint { uint16_t x, y; uint8_t id; };
// Relative trackpad: lifting/replacing a finger never teleports the cursor.
// Preserve fractional pixel motion and follow one contact across reordered samples.
class TouchCursor {
    int rx = 1920, ry = 943, finger = -1, last_x = 0, last_y = 0;
    int64_t remainder_x = 0, remainder_y = 0;
public:
    void reset();
    void set_resolution(int width, int height);
    bool update(const TouchPoint* points, size_t count, int width, int height, int& x, int& y);
};
}
