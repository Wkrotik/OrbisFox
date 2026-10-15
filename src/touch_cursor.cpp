#include "orbisfox/touch_cursor.h"
namespace orbisfox {
void TouchCursor::reset() { finger = -1; remainder_x = remainder_y = 0; }
void TouchCursor::set_resolution(int width, int height) {
    rx = width >= 2 && width <= 65535 ? width : 1920;
    ry = height >= 2 && height <= 65535 ? height : 943;
    reset();
}
bool TouchCursor::update(const TouchPoint* points, size_t count, int width, int height, int& x, int& y) {
    if (!points || !count || width <= 0 || height <= 0 || width > 16384 || height > 16384) {
        reset(); return false;
    }
    if (count > 2) count = 2;
    const TouchPoint* selected = nullptr;
    for (size_t i = 0; i < count; ++i)
        if (points[i].x < rx && points[i].y < ry && points[i].id == finger) selected = points + i;
    if (!selected) {
        reset();
        for (size_t i = 0; i < count; ++i)
            if (points[i].x < rx && points[i].y < ry) { selected = points + i; break; }
        if (!selected) return false;
        finger = selected->id; last_x = selected->x; last_y = selected->y;
        return false;
    }
    int dx = int(selected->x) - last_x, dy = int(selected->y) - last_y;
    last_x = selected->x; last_y = selected->y;
    if (dx > rx / 2 || dx < -rx / 2 || dy > ry / 2 || dy < -ry / 2) {
        remainder_x = remainder_y = 0; return false; // Discontinuous/stale sensor sample.
    }
    int64_t sx = int64_t(dx) * width + remainder_x, sy = int64_t(dy) * height + remainder_y;
    int mx = int(sx / rx), my = int(sy / ry);
    remainder_x = sx % rx; remainder_y = sy % ry;
    int nx = x + mx, ny = y + my;
    if (nx < 0) nx = 0;
    if (nx >= width) nx = width - 1;
    if (ny < 0) ny = 0;
    if (ny >= height) ny = height - 1;
    bool changed = nx != x || ny != y;
    x = nx; y = ny;
    return changed;
}
}
