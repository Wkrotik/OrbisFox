#include "orbisfox/surface.h"
namespace orbisfox {
void draw_probe(Surface s, const Diagnostics& d, int page, int cx, int cy) {
    constexpr Color bg{19,27,47,255}, fg{225,233,248,255};
    constexpr Color muted{157,175,201,255}, orange{245,145,45,255};
    fill_rect(s, 0, 0, s.width, s.height, bg);
    fill_rect(s, 0, 0, s.width, 112, {31,43,66,255});
    text(s, 40, 28, "ORBISFOX", 5, orange);
    text(s, 350, 43, "VERSION 0.11", 3, fg);
    text(s, 40, 138, "SPIDERMONKEY INCLUDED - NOT A WORKING BROWSER", 3, orange);
    if (page == 0) {
        text(s, 40, 204, "PRESENTER:", 3, muted);
        text(s, 250, 204, d.renderer, 3, fg);
        text(s, 40, 252, "THREADS:", 3, muted); text(s, 250, 252, d.threads, 3, fg);
        text(s, 40, 300, "RW TO RX:", 3, muted); text(s, 250, 300, d.memory, 3, fg);
        text(s, 40, 348, "ENTROPY:", 3, muted); text(s, 250, 348, d.entropy, 3, fg);
        text(s, 40, 396, "STORAGE:", 3, muted); text(s, 250, 396, d.storage, 3, fg);
        text(s, 40, 442, "CONTROLLER:", 2, muted); text(s, 250, 442, d.controller, 2, fg);
        text(s, 40, 478, "HTML/CSS LAYOUT / NETWORKING STILL TO PORT", 3, fg);
        text(s, 40, 510, "VIDEOOUT DEFAULT - PIGLET IS EXPERIMENTAL", 3, muted);
        text(s, 40, 554, d.engine, 2, orange);
        text(s, 40, 590, d.runtime, 2, muted);
    } else {
        text(s, 40, 204, "GPU DETAILS:", 3, muted);
        text(s, 40, 246, d.graphics, 2, fg);
        for (int i = 0; i < 3; ++i)
            fill_rect(s, 40 + i * 160, 370, 140, 80,
                      i == 0 ? Color{255,0,0,255} : i == 1 ? Color{0,255,0,255} : Color{0,0,255,255});
        text(s, 40, 478, "TEST: RED / GREEN / BLUE - TOP LEFT ORIGIN", 3, fg);
        text(s, 40, 524, "NO NETWORK ACCESS IN THIS PROTOTYPE", 3, muted);
    }
    fill_rect(s, 0, 630, s.width, 90, {31,43,66,255});
    text(s, 40, 660, "CROSS: PAGE   STICK/TOUCH: CURSOR   OPTIONS: EXIT", 3, fg);
    fill_rect(s, cx - 8, cy - 1, 17, 3, orange);
    fill_rect(s, cx - 1, cy - 8, 3, 17, orange);
}
} // namespace orbisfox
