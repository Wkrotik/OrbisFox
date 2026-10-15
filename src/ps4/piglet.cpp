// SPDX-License-Identifier: GPL-3.0-or-later
// OpenOrbis sample-derived integration; see LICENSES/README.md.
#include "orbisfox/presenter.h"
#include "orbisfox/shader_table.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <orbis/Pigletv2VSH.h>
#include <orbis/libkernel.h>

namespace orbisfox {
// All functions are resolved after loading firmware modules. No Piglet binaries
// or copyrighted shader blobs are bundled in our PKG.
#define PIGLET_FUNCTIONS(X) \
    X(scePigletSetConfigurationVSH) \
    X(eglGetDisplay) X(eglInitialize) X(eglBindAPI) X(eglChooseConfig) \
    X(eglCreateWindowSurface) X(eglCreateContext) X(eglMakeCurrent) \
    X(eglSwapInterval) X(eglSwapBuffers) X(eglDestroySurface) \
    X(eglDestroyContext) X(eglTerminate) X(eglGetError) \
    X(glGetString) X(glGetError) X(glGenTextures) X(glBindTexture) \
    X(glTexImage2D) X(glTexSubImage2D) X(glTexParameteri) X(glPixelStorei) \
    X(glDeleteTextures) X(glCreateShader) X(glShaderBinary) X(glCreateProgram) \
    X(glAttachShader) X(glLinkProgram) X(glGetProgramiv) X(glGetProgramInfoLog) \
    X(glDeleteShader) X(glDeleteProgram) X(glGetUniformLocation) \
    X(glGetAttribLocation) X(glUseProgram) X(glUniform1f) X(glUniform1i) \
    X(glUniformMatrix4fv) X(glVertexAttribPointer) X(glEnableVertexAttribArray) \
    X(glActiveTexture) X(glDrawArrays) X(glViewport) X(glDisable) X(glFinish) \
    X(glGetShaderiv) X(glGenBuffers) X(glBindBuffer) X(glBufferData) X(glDeleteBuffers)
struct Api {
#define DECLARE(name) decltype(&::name) name = nullptr;
    PIGLET_FUNCTIONS(DECLARE)
#undef DECLARE
};
// Validate the complete span before copying; bounded loop handles mappings
// crossed by a string or shader blob. No signal-handler recovery or raw probing.
static bool mapped_read(void*, uintptr_t address, void* destination, size_t bytes) {
    if (!address || !destination || !bytes || address > UINTPTR_MAX - bytes) return false;
    const uintptr_t limit = address + bytes;
    for (uintptr_t cursor = address; cursor < limit;) {
        void* start = nullptr;
        void* end = nullptr;
        int32_t protection = 0;
        int rc = sceKernelQueryMemoryProtection(reinterpret_cast<void*>(cursor), &start, &end, &protection);
        uintptr_t low = reinterpret_cast<uintptr_t>(start), high = reinterpret_cast<uintptr_t>(end);
        if (rc < 0 || !(protection & ORBIS_KERNEL_PROT_CPU_READ) || low > cursor || high <= cursor) {
            log("Memory read rejected: address=%p bytes=%zu query=0x%x range=%p..%p prot=0x%x",
                reinterpret_cast<void*>(address), bytes, rc, start, end, protection);
            return false;
        }
        cursor = high < limit ? high : limit;
    }
    memcpy(destination, reinterpret_cast<const void*>(address), bytes);
    return true;
}

class Piglet final : public Presenter {
    Api api;
    int piglet = -1, shaders = -1;
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLContext context = EGL_NO_CONTEXT;
    EGLSurface window = EGL_NO_SURFACE;
    OrbisPglWindow native_window{};
    GLuint texture = 0, program = 0, vertex_shader = 0, fragment_shader = 0, quad = 0;
    uint8_t* vertex_binary = nullptr;
    uint8_t* fragment_binary = nullptr;
    bool current = false, first_frame = true;
    GLint model = -1, projection = -1, space = -1, opacity = -1, sampler = -1, vertex = -1;
    int width = 0, height = 0;
    bool ready = false;
    char information[512] = "PIGLET NOT INITIALIZED";

    int load_module(const char* filename) {
        const char* sandbox = sceKernelGetFsSandboxRandomWord();
        if (!sandbox || !*sandbox) return -1;
        char path[256];
        int n = snprintf(path, sizeof(path), "/%s/common/lib/%s", sandbox, filename);
        if (n < 0 || (size_t)n >= sizeof(path)) return -1;
        int start_result = 0;
        int handle = (int32_t)sceKernelLoadStartModule(path, 0, nullptr, 0, nullptr, &start_result);
        log("load %s: handle=%d start=%d", filename, handle, start_result);
        return handle;
    }
    bool resolve() {
#define LOAD(name) do { \
        void* symbol = nullptr; \
        if (sceKernelDlsym(piglet, #name, &symbol) < 0 || !symbol) { \
            log("Piglet missing symbol %s", #name); return false; \
        } \
        api.name = reinterpret_cast<decltype(api.name)>(symbol); \
    } while (0);
        PIGLET_FUNCTIONS(LOAD)
#undef LOAD
        return true;
    }
    bool check_gl(const char* stage) {
        GLenum error = api.glGetError();
        log("Piglet %s: GL=0x%x", stage, error);
        return error == GL_NO_ERROR;
    }
    bool create_program() {
        log("Shader table: resolving scePrecompiledShaderEntries");
        void* symbol = nullptr;
        int rc = sceKernelDlsym(shaders, "scePrecompiledShaderEntries", &symbol);
        log("Shader table: dlsym rc=0x%x address=%p", rc, symbol);
        if (rc < 0 || !symbol) return false;
        MemoryReader reader{nullptr, mapped_read};
        FirmwareShaderEntry first{};
        log("Shader table: validating first 40-byte record");
        if (!mapped_read(nullptr, reinterpret_cast<uintptr_t>(symbol), &first, sizeof(first))) return false;
        log("Shader table first record: name=%p length=%llu code=%p",
            static_cast<const void*>(first.name), (unsigned long long)first.length, static_cast<const void*>(first.code));
        const char* names[] = {"texmap/v_2.vert", "texmap/f_2.frag"};
        ShaderLookup matches[2]{};
        for (int i = 0; i < 2; ++i) {
            log("Shader lookup begin: %s", names[i]);
            matches[i] = find_firmware_shader(reader, reinterpret_cast<uintptr_t>(symbol), names[i]);
            log("Shader lookup end: %s: %s inspected=%zu", names[i],
                shader_lookup_status(matches[i].status), matches[i].inspected);
            if (matches[i].status != ShaderLookupStatus::found) return false;
        }
        auto snapshot = [&](const ShaderLookup& match, uint8_t*& bytes) {
            bytes = static_cast<uint8_t*>(malloc((size_t)match.entry.length));
            return bytes && mapped_read(nullptr, reinterpret_cast<uintptr_t>(match.entry.code),
                                        bytes, (size_t)match.entry.length);
        };
        log("Shader binaries: copying verified firmware spans");
        if (!snapshot(matches[0], vertex_binary) || !snapshot(matches[1], fragment_binary)) return false;
        log("Shader binaries ready: vertex=%llu fragment=%llu bytes",
            (unsigned long long)matches[0].entry.length, (unsigned long long)matches[1].entry.length);
        log("Shader objects: glCreateShader / glCreateProgram begin");
        vertex_shader = api.glCreateShader(GL_VERTEX_SHADER);
        fragment_shader = api.glCreateShader(GL_FRAGMENT_SHADER);
        program = api.glCreateProgram();
        if (!check_gl("create shader objects") || !vertex_shader || !fragment_shader || !program) return false;
        log("Vertex shader: glShaderBinary begin");
        api.glShaderBinary(1, &vertex_shader, 0, vertex_binary, (GLsizei)matches[0].entry.length);
        if (!check_gl("vertex glShaderBinary")) return false;
        log("Fragment shader: glShaderBinary begin");
        api.glShaderBinary(1, &fragment_shader, 0, fragment_binary, (GLsizei)matches[1].entry.length);
        if (!check_gl("fragment glShaderBinary")) return false;
        GLint vcompiled = 0, fcompiled = 0;
        api.glGetShaderiv(vertex_shader, GL_COMPILE_STATUS, &vcompiled);
        api.glGetShaderiv(fragment_shader, GL_COMPILE_STATUS, &fcompiled);
        log("Shader compile status: vertex=%d fragment=%d", vcompiled, fcompiled);
        if (!vcompiled || !fcompiled || !check_gl("shader status")) return false;
        log("Shader program: attach / link begin");
        api.glAttachShader(program, vertex_shader); api.glAttachShader(program, fragment_shader);
        if (!check_gl("attach shaders")) return false;
        api.glLinkProgram(program);
        if (!check_gl("glLinkProgram")) return false;
        GLint linked = 0;
        api.glGetProgramiv(program, GL_LINK_STATUS, &linked);
        log("Shader program: link status=%d", linked);
        if (!linked) {
            char message[512] = {};
            GLsizei written = 0;
            api.glGetProgramInfoLog(program, sizeof(message) - 1, &written, message);
            log("Texture shader link failed: %s", message);
            return false;
        }
        log("Shader program: uniform / attribute lookup begin");
        model = api.glGetUniformLocation(program, "u_modelViewMatrix");
        projection = api.glGetUniformLocation(program, "u_projectionMatrix");
        space = api.glGetUniformLocation(program, "u_textureSpaceMatrix");
        opacity = api.glGetUniformLocation(program, "u_opacity");
        sampler = api.glGetUniformLocation(program, "s_sampler");
        vertex = api.glGetAttribLocation(program, "a_vertex");
        log("Shader locations: model=%d projection=%d space=%d opacity=%d sampler=%d vertex=%d",
            model, projection, space, opacity, sampler, vertex);
        return check_gl("shader locations") && model >= 0 && projection >= 0 && space >= 0
            && opacity >= 0 && sampler >= 0 && vertex >= 0;
    }
    void shutdown() {
        ready = false;
        if (current) {
            log("Piglet shutdown: deleting GL resources");
            if (quad) api.glDeleteBuffers(1, &quad);
            if (texture) api.glDeleteTextures(1, &texture);
            if (program) api.glDeleteProgram(program);
            if (vertex_shader) api.glDeleteShader(vertex_shader);
            if (fragment_shader) api.glDeleteShader(fragment_shader);
        }
        if (context != EGL_NO_CONTEXT) {
            log("Piglet shutdown: releasing EGL context");
            api.eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
            api.eglDestroyContext(display, context);
        }
        if (window != EGL_NO_SURFACE) {
            log("Piglet shutdown: destroying EGL surface");
            api.eglDestroySurface(display, window);
        }
        if (display != EGL_NO_DISPLAY && api.eglTerminate) {
            log("Piglet shutdown: eglTerminate");
            api.eglTerminate(display);
        }
        display = EGL_NO_DISPLAY; context = EGL_NO_CONTEXT; window = EGL_NO_SURFACE;
        current = false;
        texture = program = vertex_shader = fragment_shader = quad = 0;
        free(vertex_binary); free(fragment_binary);
        vertex_binary = fragment_binary = nullptr;
        int result = 0;
        if (shaders >= 0) {
            log("Piglet shutdown: unloading shader module");
            sceKernelStopUnloadModule(shaders, 0, nullptr, 0, nullptr, &result);
        }
        if (piglet >= 0) {
            log("Piglet shutdown: unloading Piglet module");
            sceKernelStopUnloadModule(piglet, 0, nullptr, 0, nullptr, &result);
            log("Piglet shutdown complete");
        }
        shaders = piglet = -1;
        api = {};
    }
    bool configure(int w, int h) {
        width = w; height = h;
        piglet = load_module("libScePigletv2VSH.sprx");
        if (piglet < 0 || !resolve()) return false;
        shaders = load_module("libScePrecompiledShaders.sprx");
        if (shaders < 0) return false;
        OrbisPglConfig cfg = {};
        cfg.size = sizeof(cfg);
        // Reverse-engineered values from the OpenOrbis Piglet example.
        cfg.flags = ORBIS_PGL_FLAGS_USE_COMPOSITE_EXT | ORBIS_PGL_FLAGS_USE_FLEXIBLE_MEMORY | 0x60;
        cfg.processOrder = 1;
        cfg.systemSharedMemorySize = 250 * 1024 * 1024;
        cfg.videoSharedMemorySize = 512 * 1024 * 1024;
        cfg.maxMappedFlexibleMemory = 170 * 1024 * 1024;
        cfg.drawCommandBufferSize = cfg.lcueResourceBufferSize = 1024 * 1024;
        cfg.dbgPosCmd_0x40 = w; cfg.dbgPosCmd_0x44 = h; cfg.unk_0x5C = 2;
        if (!api.scePigletSetConfigurationVSH(&cfg)) return false;
        display = api.eglGetDisplay(EGL_DEFAULT_DISPLAY);
        EGLint major = 0, minor = 0;
        if (display == EGL_NO_DISPLAY || !api.eglInitialize(display, &major, &minor)) return false;
        if (!api.eglBindAPI(EGL_OPENGL_ES_API)) return false;
        const EGLint attributes[] = {
            EGL_RED_SIZE,8, EGL_GREEN_SIZE,8, EGL_BLUE_SIZE,8, EGL_ALPHA_SIZE,8,
            EGL_DEPTH_SIZE,0, EGL_STENCIL_SIZE,0,
            EGL_RENDERABLE_TYPE,EGL_OPENGL_ES2_BIT, EGL_SURFACE_TYPE,EGL_WINDOW_BIT, EGL_NONE
        };
        EGLConfig config = {};
        EGLint count = 0;
        if (!api.eglChooseConfig(display, attributes, &config, 1, &count) || count < 1) return false;
        native_window = {0, (khronos_uint32_t)w, (khronos_uint32_t)h, 0};
        const EGLint wattrs[] = {EGL_RENDER_BUFFER,EGL_BACK_BUFFER,EGL_NONE};
        const EGLint cattrs[] = {EGL_CONTEXT_CLIENT_VERSION,2,EGL_NONE};
        window = api.eglCreateWindowSurface(display, config, &native_window, wattrs);
        if (window == EGL_NO_SURFACE) return false;
        context = api.eglCreateContext(display, config, EGL_NO_CONTEXT, cattrs);
        if (context == EGL_NO_CONTEXT || !api.eglMakeCurrent(display, window, window, context)) return false;
        current = true;
        log("Piglet: requesting swap interval 0 (interval 1 blocks on the tested console)");
        if (!api.eglSwapInterval(display, 0)) return false;
        const char* version = reinterpret_cast<const char*>(api.glGetString(GL_VERSION));
        const char* renderer = reinterpret_cast<const char*>(api.glGetString(GL_RENDERER));
        snprintf(information, sizeof(information), "EGL %d.%d\nGL: %.100s\nGPU: %.100s", major, minor,
                 version ? version : "UNKNOWN", renderer ? renderer : "UNKNOWN");
        log("%s", information);
        const char* extensions = reinterpret_cast<const char*>(api.glGetString(GL_EXTENSIONS));
        log("GL extensions: %s", extensions ? extensions : "UNAVAILABLE");
        if (!check_gl("context ready") || !create_program()) return false;
        log("Texture: creation / configuration begin");
        api.glGenTextures(1, &texture);
        if (!texture || !check_gl("glGenTextures")) return false;
        api.glBindTexture(GL_TEXTURE_2D, texture);
        api.glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        api.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        api.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        api.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        api.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        if (!check_gl("texture parameters")) return false;
        log("Texture: glTexImage2D %dx%d begin", w, h);
        api.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        if (!check_gl("glTexImage2D")) return false;
        const GLfloat vertices[] = {0,1,0,1, 1,0,1,0, 0,0,0,0, 0,1,0,1, 1,1,1,1, 1,0,1,0};
        log("Quad VBO: creation / upload begin");
        api.glGenBuffers(1, &quad);
        if (!quad) return false;
        api.glBindBuffer(GL_ARRAY_BUFFER, quad);
        api.glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
        return check_gl("quad VBO upload");
    }
public:
    ~Piglet() override { shutdown(); }
    bool init(int w, int h) override {
        shutdown();
        if (w <= 0 || h <= 0) return false;
        if (!configure(w, h)) {
            if (api.eglGetError) log("Piglet init failed: EGL=0x%x", api.eglGetError());
            shutdown(); return false;
        }
        ready = true; first_frame = true;
        log("Piglet initialization complete");
        return true;
    }
    bool present(const Surface& s) override {
        if (!ready || !valid(s) || s.width != width || s.height != height || s.stride != (size_t)width * 4) return false;
        const GLfloat identity[] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
        // Unit quad to clip space; y=0 is the top of the screen and source.
        const GLfloat clip[] = {2,0,0,0, 0,-2,0,0, 0,0,1,0, -1,1,0,1};
        if (first_frame) log("First Piglet frame: state setup begin");
        api.glViewport(0, 0, width, height);
        api.glDisable(GL_BLEND); api.glDisable(GL_DEPTH_TEST); api.glDisable(GL_SCISSOR_TEST);
        api.glUseProgram(program);
        api.glActiveTexture(GL_TEXTURE0);
        api.glBindTexture(GL_TEXTURE_2D, texture);
        if (first_frame) log("First Piglet frame: texture upload begin");
        api.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, s.pixels);
        if (first_frame && !check_gl("first texture upload")) return false;
        api.glUniformMatrix4fv(model, 1, GL_FALSE, identity);
        api.glUniformMatrix4fv(projection, 1, GL_FALSE, clip);
        api.glUniformMatrix4fv(space, 1, GL_FALSE, identity);
        api.glUniform1f(opacity, 1.0f); api.glUniform1i(sampler, 0);
        api.glBindBuffer(GL_ARRAY_BUFFER, quad);
        api.glVertexAttribPointer(vertex, 4, GL_FLOAT, GL_FALSE, 4 * sizeof(GLfloat), nullptr);
        api.glEnableVertexAttribArray(vertex);
        if (first_frame) log("First Piglet frame: glDrawArrays begin");
        api.glDrawArrays(GL_TRIANGLES, 0, 6);
        // Synchronous prototype. Replace with fences/ring buffers after measuring.
        if (first_frame) log("First Piglet frame: glFinish begin");
        api.glFinish();
        GLenum error = api.glGetError();
        if (error != GL_NO_ERROR) { log("Piglet frame failed: GL=0x%x", error); return false; }
        if (first_frame) log("First Piglet frame: eglSwapBuffers begin");
        if (!api.eglSwapBuffers(display, window)) {
            log("Piglet swap failed: EGL=0x%x", api.eglGetError()); return false;
        }
        if (first_frame) log("First Piglet frame: complete");
        first_frame = false;
        return true;
    }
    void stop() override { shutdown(); }
    const char* name() const override { return "PIGLET GLES2 GPU BLIT"; }
    const char* details() const override { return information; }
};
Presenter& piglet_presenter() { static Piglet renderer; return renderer; }
} // namespace orbisfox
