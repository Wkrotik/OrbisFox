#include "orbisfox/touch_cursor.h"
#include <assert.h>
#include <stdio.h>
using namespace orbisfox;
int main() {
    TouchCursor cursor; cursor.set_resolution(1920, 960);
    int x = 640, y = 360;
    TouchPoint p{100,100,7};
    assert(!cursor.update(&p, 1, 1280, 720, x, y)); // Landing doesn't jump.
    p.x = 130; p.y = 140;
    assert(cursor.update(&p, 1, 1280, 720, x, y));
    assert(x == 660 && y == 390);
    assert(!cursor.update(nullptr, 0, 1280, 720, x, y));
    p = {1000, 800, 8};
    assert(!cursor.update(&p, 1, 1280, 720, x, y));
    assert(x == 660 && y == 390);
    TouchPoint fingers[2] = {{100,100,9}, {1003,804,8}};
    assert(cursor.update(fingers, 2, 1280, 720, x, y));
    assert(x == 662 && y == 393); // Follow ID 8 even when order changes.
    cursor.reset(); p = {100,100,0};
    cursor.update(&p, 1, 1280, 720, x, y);
    int original = x;
    ++p.x; cursor.update(&p, 1, 1280, 720, x, y);
    ++p.x; cursor.update(&p, 1, 1280, 720, x, y);
    ++p.x; cursor.update(&p, 1, 1280, 720, x, y);
    assert(x == original + 2); // Small motions accumulate fractional pixels.
    p.x = 65535;
    assert(!cursor.update(&p, 1, 1280, 720, x, y)); // Invalid sensor coordinates.
    p = {100,100,1}; cursor.update(&p, 1, 1280, 720, x, y);
    p.x = 1800; assert(!cursor.update(&p, 1, 1280, 720, x, y)); // Implausible discontinuity.
    cursor.reset(); x = 1279; y = 719; p = {100,100,2};
    cursor.update(&p, 1, 1280, 720, x, y); p.x += 30; p.y += 30;
    cursor.update(&p, 1, 1280, 720, x, y); assert(x == 1279 && y == 719);
    cursor.reset(); x = 0; y = 0; p = {100,100,2};
    cursor.update(&p, 1, 1280, 720, x, y); p.x -= 30; p.y -= 30;
    cursor.update(&p, 1, 1280, 720, x, y); assert(x == 0 && y == 0);
    puts("touchpad: relative motion, lift, contact IDs, subpixels, invalid samples, discontinuities and edges passed");
}
