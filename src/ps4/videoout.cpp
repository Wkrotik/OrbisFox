// SPDX-License-Identifier: GPL-3.0-or-later
// OpenOrbis sample-derived integration; see LICENSES/README.md.
#include "orbisfox/presenter.h"
#include "orbisfox/module_binding.h"
#include <orbis/libkernel.h>
#include <orbis/VideoOut.h>
#include <orbis/Sysmodule.h>

namespace orbisfox {
class VideoOut final : public Presenter {
    ModuleBinding module;
    struct Api {
        decltype(&::sceVideoOutOpen) open = nullptr;
        decltype(&::sceVideoOutClose) close = nullptr;
        decltype(&::sceVideoOutRegisterBuffers) register_buffers = nullptr;
        decltype(&::sceVideoOutUnregisterBuffers) unregister_buffers = nullptr;
        decltype(&::sceVideoOutSubmitFlip) submit_flip = nullptr;
        decltype(&::sceVideoOutSetBufferAttribute) set_attributes = nullptr;
        decltype(&::sceVideoOutSetFlipRate) set_flip_rate = nullptr;
        decltype(&::sceVideoOutGetFlipStatus) get_flip_status = nullptr;
    } api;
    bool bind_api() {
        api = {};
        return module.open(ps4_module_backend(), "libSceVideoOut", ORBIS_SYSMODULE_INTERNAL_VIDEO_OUT)
            && module.bind("sceVideoOutOpen", api.open)
            && module.bind("sceVideoOutClose", api.close)
            && module.bind("sceVideoOutRegisterBuffers", api.register_buffers)
            && module.bind("sceVideoOutUnregisterBuffers", api.unregister_buffers)
            && module.bind("sceVideoOutSubmitFlip", api.submit_flip)
            && module.bind("sceVideoOutSetBufferAttribute", api.set_attributes)
            && module.bind("sceVideoOutSetFlipRate", api.set_flip_rate)
            && module.bind("sceVideoOutGetFlipStatus", api.get_flip_status);
    }
    int handle = -1, registration = -1;
    void* memory = nullptr;
    void* buffers[2] = {};
    off_t offset = 0;
    size_t allocation = 0;
    int width = 0, height = 0, active = 0;
    int64_t frame = 1;
    void shutdown() {
        if (handle >= 0) {
            log("VideoOut shutdown: unregister / close begin");
            if (registration >= 0) api.unregister_buffers(handle, registration);
            api.close(handle);
        }
        if (memory) sceKernelMunmap(memory, allocation);
        if (allocation) sceKernelReleaseDirectMemory(offset, allocation);
        handle = registration = -1; memory = nullptr; allocation = 0;
    }
    bool configure(int w, int h) {
        width = w; height = h;
        constexpr size_t alignment = 2 * 1024 * 1024;
        size_t bytes = (size_t)w * h * 4;
        size_t slot_size = (bytes + alignment - 1) & ~(alignment - 1);
        size_t total = 2 * slot_size;
        if (!bind_api()) {
            log("VideoOut init: required service module/API unavailable; refusing open call");
            return false;
        }
        log("VideoOut init: resolved sceVideoOutOpen begin");
        handle = api.open(ORBIS_VIDEO_USER_MAIN, ORBIS_VIDEO_OUT_BUS_MAIN, 0, nullptr);
        log("VideoOut init: sceVideoOutOpen returned handle=%d", handle);
        if (handle < 0) { log("VideoOut open: 0x%x", handle); return false; }
        log("VideoOut init: allocating %zu bytes direct memory", total);
        int rc = sceKernelAllocateDirectMemory(0, sceKernelGetDirectMemorySize(), total, alignment, 3, &offset);
        if (rc < 0) { log("Direct allocation: 0x%x", rc); return false; }
        allocation = total;
        log("VideoOut init: mapping direct memory");
        rc = sceKernelMapDirectMemory(&memory, total, 0x33, 0, offset, alignment);
        if (rc < 0) { log("Direct mapping: 0x%x", rc); return false; }
        buffers[0] = memory; buffers[1] = static_cast<uint8_t*>(memory) + slot_size;
        OrbisVideoOutBufferAttribute attr = {};
        // B8G8R8A8 sRGB, linear, no aspect override (OpenOrbis example).
        api.set_attributes(&attr, 0x80000000, 1, 0, w, h, w);
        log("VideoOut init: registering scanout buffers");
        registration = api.register_buffers(handle, 0, buffers, 2, &attr);
        if (registration < 0) { log("Register buffers: 0x%x", registration); return false; }
        api.set_flip_rate(handle, 0);
        log("VideoOut ready: %dx%d / %zu bytes", w, h, total);
        return true;
    }
public:
    ~VideoOut() override { shutdown(); }
    bool init(int w, int h) override {
        shutdown(); active = 0; frame = 1;
        if (w <= 0 || h <= 0 || w > 4096 || h > 4096) return false;
        if (!configure(w, h)) { shutdown(); return false; }
        return true;
    }
    bool present(const Surface& s) override {
        if (!valid(s) || !memory || s.width != width || s.height != height) return false;
        if (frame == 1) log("First VideoOut frame: RGBA to BGRA copy begin");
        rgba_to_bgra(static_cast<uint8_t*>(buffers[active]), s);
        if (frame == 1) log("First VideoOut frame: submit flip begin");
        int rc = api.submit_flip(handle, active, ORBIS_VIDEO_OUT_FLIP_VSYNC, frame);
        if (rc < 0) { log("VideoOut submit: 0x%x", rc); return false; }
        // Bounded synchronous wait: no overwrite of an in-flight framebuffer.
        for (int attempt = 0; attempt < 2000; ++attempt) {
            OrbisVideoOutFlipStatus status = {};
            rc = api.get_flip_status(handle, &status);
            if (rc < 0) { log("VideoOut status: 0x%x", rc); return false; }
            if (status.flipArg == frame) {
                if (frame == 1) log("First VideoOut frame: flip complete");
                active ^= 1; ++frame; return true;
            }
            sceKernelUsleep(1000);
        }
        log("VideoOut flip timed out"); return false;
    }
    void stop() override { shutdown(); }
    const char* name() const override { return "VIDEOOUT CPU SCANOUT"; }
    const char* details() const override { return "NATIVE BGRA8 SCANOUT\nCPU FRAME PRESENTATION\nNO GPU RASTERIZATION"; }
};
Presenter& videoout_presenter() { static VideoOut renderer; return renderer; }
} // namespace orbisfox
