#include "orbisfox/stick_cursor.h"
#include <assert.h>
using orbisfox::stick_cursor_delta;
int main() {
    for (int v = 111; v <= 145; ++v) assert(stick_cursor_delta(v) == 0);
    assert(stick_cursor_delta(110) == -1);
    assert(stick_cursor_delta(146) == 1);
    assert(stick_cursor_delta(0) == -9);
    assert(stick_cursor_delta(255) == 9);
    for (int v = 0; v < 255; ++v) assert(stick_cursor_delta(v) <= stick_cursor_delta(v + 1));
    for (int d = 0; d <= 127; ++d) assert(stick_cursor_delta(128 - d) == -stick_cursor_delta(128 + d));
    for (int v = 0; v <= 255; ++v) {
        orbisfox::StickCursor1_5 fast;
        int total = 0;
        for (int frame = 0; frame < 1000; ++frame) total += fast.update(v);
        assert(total * 2 == 3000 * stick_cursor_delta(v));
    }
    for (int d = 0; d <= 127; ++d) {
        orbisfox::StickCursor1_5 positive, negative;
        for (int frame = 0; frame < 100; ++frame)
            assert(positive.update(128 + d) == -negative.update(128 - d));
    }
    orbisfox::StickCursor1_5 x, y;
    assert(x.update(255) == 13); assert(x.update(255) == 14);
    assert(y.update(255) == 13); // independent axis carry
    assert(x.update(128) == 0); assert(x.update(255) == 13);
    for (int v = 111; v <= 145; ++v) assert(x.update(v) == 0);
    assert(x.update(0) == -13); assert(x.update(255) == 13); // opposing halves cancel
}
