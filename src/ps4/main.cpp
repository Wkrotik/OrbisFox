#include "orbisfox/presenter.h"
#include "orbisfox/artwork.h"
#include "orbisfox/ps4_services.h"
#include "orbisfox/swgl_canvas.h"
#include "orbisfox/touch_cursor.h"
#include "orbisfox/rust_runtime.h"
#include "orbisfox/stick_cursor.h"
#include "orbisfox/js_canvas.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <orbis/libkernel.h>

using namespace orbisfox;
static int clamp(int value, int low, int high) { return value < low ? low : value > high ? high : value; }
static void js_log(const char* message) { log("%s", message); }
int main() {
    setvbuf(stdout, nullptr, _IONBF, 0);
#ifdef ORBISFOX_VIDEOOUT_ONLY
    constexpr bool videoout_only = true;
#else
    constexpr bool videoout_only = false;
#endif
    Diagnostics diagnostics = run_platform_probes(videoout_only);
    constexpr int width = 1280, height = 720;
    auto* pixels = static_cast<uint8_t*>(malloc((size_t)width * height * 4));
    if (!pixels) { log("Surface allocation failed"); close_log(); return EXIT_FAILURE; }
    Surface surface{pixels, width, height, (size_t)width * 4};
#ifdef ORBISFOX_VIDEOOUT_ONLY
    Presenter* presenter = &videoout_presenter();
    if (!presenter->init(width, height)) {
        log("VideoOut-only initialization failed"); free(pixels); close_log(); return EXIT_FAILURE;
    }
#else
    // 0.03 blocks in Piglet's first eglSwapBuffers on the tested console.
    // Keep the operational VideoOut path as the default, not a blocked input loop.
    Presenter* presenter = &videoout_presenter();
    bool test_piglet = access("/data/orbisfox/force-piglet", F_OK) == 0
        && access("/data/orbisfox/force-videoout", F_OK) != 0;
    if (test_piglet) {
        log("Experimental Piglet requested by marker");
        presenter = &piglet_presenter();
        if (!presenter->init(width, height)) presenter = &videoout_presenter();
    }
    if (presenter == &videoout_presenter() && !presenter->init(width, height)) {
        log("No usable presenter"); free(pixels); close_log(); return EXIT_FAILURE;
    }
#endif
    diagnostics.renderer = presenter->name(); diagnostics.graphics = presenter->details();
    int page = 0, x = width / 2, y = height / 2;
    // Prove graphics independently of UserService/Pad initialization. In 0.02
    // an input-service crash prevented us from submitting even a single frame.
    log("First UI frame: CPU drawing begin - BEFORE controller initialization");
    bool splash_loaded = load_artwork("/app0/assets/splash.rgba", surface);
    log("OrbisFox splash artwork: %s", splash_loaded ? "loaded" : "unavailable - using UI fallback");
    if (!splash_loaded) draw_probe(surface, diagnostics, page, x, y);
    log("First UI frame: presenter begin");
    if (!presenter->present(surface)) {
        log("First UI frame failed");
        presenter->stop(); free(pixels); close_log(); return EXIT_FAILURE;
    }
    log("First UI frame: presented successfully");
    hide_splash_screen();
    // Display the user's artwork ourselves as well as shipping the PS4 menu
    // pictures. Keep the system splash until a complete application frame exists.
    if (splash_loaded) sceKernelUsleep(900000);

    Controller controller;
    if (access("/data/orbisfox/skip-controller", F_OK) == 0) {
        log("Controller: skipped by /data/orbisfox/skip-controller marker");
        diagnostics.controller = "DISABLED BY MARKER";
    } else {
        bool connected = controller.init();
        diagnostics.controller = connected ? "PAD HANDLE OPEN" : "UNAVAILABLE";
        if (!connected) log("Controller unavailable: OrbisFox remains open; close using PS4 system UI");
    }
    log("Presenter=%s controller=%s", presenter->name(), diagnostics.controller);
    SwglCanvas engine;
    JsCanvas javascript;
    bool js_attempted = false, js_ready = false, first_js_frame = true;
    bool js_click = false;
    const uint64_t script_epoch = sceKernelGetProcessTime();
    bool engine_attempted = false, engine_ready = false, first_engine_frame = true;
    diagnostics.engine = "FIREFOX SWGL AVAILABLE - CROSS TO SHADER PAGE";
    TouchCursor touch;
    touch.set_resolution(controller.touch_resolution_x(), controller.touch_resolution_y());
    bool exit_failed = false;
    uint32_t previous = 0;
    bool dirty = true;
    int result = EXIT_SUCCESS;
    for (;;) {
        OrbisPadData input{};
        if (controller.poll(input)) {
            uint32_t pressed = input.buttons & ~previous;
            previous = input.buttons;
            if (pressed & ORBIS_PAD_BUTTON_OPTIONS) {
                log("Options pressed: normal exit requested");
                request_system_exit(); // Success does not return; OS owns resource teardown.
                exit_failed = true; dirty = true;
            }
            if (pressed & ORBIS_PAD_BUTTON_CROSS) { page = (page + 1) % 4; dirty = true; }
            if ((pressed & ORBIS_PAD_BUTTON_CIRCLE) && page == 0) js_click = true;
            if ((pressed & ORBIS_PAD_BUTTON_TRIANGLE) && js_ready) {
                js_ready = javascript.load_demo("/app0/assets/playground.js");
                first_js_frame = true; page = 0; dirty = true;
                log("SpiderMonkey: script reload %s", js_ready ? "OK" : javascript.error());
            }
            if (pressed & ORBIS_PAD_BUTTON_SQUARE) {
                diagnostics.runtime = probe_rust_runtime() ? "RUST ABI / ALLOCATION / UTF-8 OK" : "RUST RUNTIME TEST FAILED - SEE LOG";
                page = 1; dirty = true;
            }
            int nx = clamp(x + stick_cursor_delta(input.leftStick.x), 10, width - 11);
            int ny = clamp(y + stick_cursor_delta(input.leftStick.y), 10, height - 11);
            TouchPoint contacts[2]{};
            size_t count = input.touch.fingers > 2 ? 2 : input.touch.fingers;
            for (size_t i = 0; i < count; ++i)
                contacts[i] = {input.touch.touch[i].x, input.touch.touch[i].y, input.touch.touch[i].finger};
            touch.update(contacts, count, width, height, nx, ny);
            nx = clamp(nx, 10, width - 11); ny = clamp(ny, 10, height - 11);
            if (nx != x || ny != y) dirty = true;
            x = nx; y = ny;
        } else { previous = 0; touch.reset(); }
        if (page == 0) dirty = true; // JavaScript owns the animation and input response.
        if (dirty) {
            if (page == 0) {
                if (!js_attempted) {
                    js_attempted = true;
                    log("SpiderMonkey: native interpreter initialization begin AFTER controller setup");
                    if (access("/data/orbisfox/skip-javascript", F_OK) == 0) {
                        log("SpiderMonkey: skipped by diagnostic marker");
                    } else {
                        js_ready = javascript.init(js_log) && javascript.load_demo("/app0/assets/playground.js");
                    }
                    log("SpiderMonkey: initialization %s", js_ready ? "OK" : javascript.error());
                    if (!js_ready) javascript.stop();
                }
                const uint64_t begin = sceKernelGetProcessTime();
                const double elapsed = static_cast<double>(begin - script_epoch) / 1000.0;
                bool rendered = js_ready && javascript.render(surface, x, y, js_click, elapsed);
                const uint64_t frame_time = sceKernelGetProcessTime() - begin;
                js_click = false;
                if (first_js_frame) {
                    log("SpiderMonkey: first live JavaScript frame %s - %u native drawing commands - %llu microseconds",
                        rendered ? "OK" : "FAILED", javascript.commands(), (unsigned long long)frame_time);
                    first_js_frame = false;
                }
                if (!rendered) {
                    fill_rect(surface, 0, 0, width, height, {11,17,32,255});
                    text(surface, 40, 40, "SPIDERMONKEY / JAVASCRIPT STARTUP FAILED", 3, {245,145,45,255});
                    text(surface, 40, 110, javascript.error(), 2, {225,233,248,255});
                    text(surface, 40, 180, "CROSS: DIAGNOSTICS   OPTIONS: EXIT", 3, {225,233,248,255});
                    text(surface, 40, 240, "DETAILS: /DATA/ORBISFOX/PLATFORM.LOG", 2, {157,175,201,255});
                    if (js_ready) {
                        log("SpiderMonkey: frame error - %s", javascript.error());
                        js_ready = false;
                    }
                }
            } else if (page == 3) {
                if (!engine_attempted) {
                    log("Firefox SWGL: native context / generated shader initialization begin");
                    engine_ready = engine.init(width, height);
                    engine_attempted = true;
                    diagnostics.engine = engine_ready ? "FIREFOX SWGL READY" : "FIREFOX SWGL INITIALIZATION FAILED";
                    log("Firefox SWGL: initialization %s", engine_ready ? "OK" : "FAILED");
                }
                if (first_engine_frame) log("Firefox SWGL: first native rasterization begin");
                uint64_t begin = sceKernelGetProcessTime();
                bool rendered = engine_ready && engine.render_shader_test(surface);
                uint64_t elapsed = sceKernelGetProcessTime() - begin;
                if (first_engine_frame) log("Firefox SWGL: rasterization %s, %llu microseconds",
                    rendered ? "OK" : "FAILED", (unsigned long long)elapsed);
                first_engine_frame = false;
                if (!rendered) fill_rect(surface, 0, 0, width, height, {19,27,47,255});
                text(surface, 40, 28, "FIREFOX SWGL / NATIVE CPU RENDERER", 4, {245,145,45,255});
                text(surface, 40, 90, "REAL WEBRENDER SHADER - NOT HTML/CSS LAYOUT YET", 3, {225,233,248,255});
                char status[128];
                snprintf(status, sizeof(status), "RASTERIZATION: %s - %llu MICROSECONDS", rendered ? "OK" : "FAILED",
                         (unsigned long long)elapsed);
                text(surface, 40, 150, status, 3, {225,233,248,255});
                text(surface, 40, 615, "MOZILLA REVISION: 83CEBCF5A522 - CPU BGRA TO RGBA", 2, {157,175,201,255});
                text(surface, 40, 660, "CROSS: NEXT PAGE   OPTIONS: EXIT", 3, {225,233,248,255});
                fill_rect(surface, x - 8, y - 1, 17, 3, {245,145,45,255});
                fill_rect(surface, x - 1, y - 8, 3, 17, {245,145,45,255});
            } else draw_probe(surface, diagnostics, page - 1, x, y);
            if (exit_failed) text(surface, 40, 590, "EXIT REQUEST FAILED - CLOSE USING THE PS BUTTON", 2, {245,145,45,255});
            if (!presenter->present(surface)) { result = EXIT_FAILURE; break; }
            dirty = false;
        }
        sceKernelUsleep(16000);
    }
    log("OrbisFox shutdown: closing controller and presenter");
    controller.stop();
    engine.stop();
    javascript.stop();
    shutdown_javascript_runtime();
    presenter->stop();
    free(pixels);
    log("OrbisFox exiting: %d", result);
    close_log();
    return result;
}
