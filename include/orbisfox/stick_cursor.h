#pragma once
#include <stdint.h>
namespace orbisfox {
// Same dead zone, modestly faster than the original delta / 16 mapping.
constexpr int stick_cursor_delta(uint8_t value) {
    const int delta = static_cast<int>(value) - 128;
    return delta > -18 && delta < 18 ? 0 : delta / 13;
}
// Full-Gecko cursor speed-up: exactly 1.5x the existing integer curve over
// sustained input. Keep half-pixel carry rather than rounding every frame;
// X/Y use independent instances. Neutral input discards carry (no drift).
class StickCursor1_5 {
    int remainder_ = 0;
public:
    int update(uint8_t value) {
        const int base = stick_cursor_delta(value);
        if (!base) { remainder_ = 0; return 0; }
        const int halfPixels = base * 3 + remainder_;
        remainder_ = halfPixels % 2;
        return halfPixels / 2;
    }
};
}
