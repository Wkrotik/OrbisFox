#include "orbisfox/swgl_canvas.h"
#include <stdlib.h>

namespace swgl_api {
// SWGL is a custom GL API, not the Piglet API. These declarations match the
// pinned upstream gl.cc, including integer attribute offsets and GLsizeiptr.
extern "C" {
void* CreateContext();
void MakeCurrent(void*);
void DestroyContext(void*);
void InitDefaultFramebuffer(int, int, int, int, int, void*);
void* GetColorBuffer(uint32_t, uint8_t, int32_t*, int32_t*, int32_t*);
uint32_t CreateShader(uint32_t);
void ShaderSourceByName(uint32_t, char*);
void AttachShader(uint32_t, uint32_t);
void DeleteShader(uint32_t);
uint32_t CreateProgram();
void BindAttribLocation(uint32_t, uint32_t, char*);
void LinkProgram(uint32_t);
int32_t GetLinkStatus(uint32_t);
int32_t GetUniformLocation(uint32_t, char*);
void UseProgram(uint32_t);
void GenBuffers(int, uint32_t*);
void BindBuffer(uint32_t, uint32_t);
void BufferData(uint32_t, size_t, void*, uint32_t);
void GenVertexArrays(int, uint32_t*);
void BindVertexArray(uint32_t);
void VertexAttribPointer(uint32_t, int32_t, uint32_t, bool, int32_t, uint32_t);
void EnableVertexAttribArray(uint32_t);
void SetViewport(int32_t, int32_t, int32_t, int32_t);
void ClearColor(float, float, float, float);
void Clear(uint32_t);
void UniformMatrix4fv(int32_t, int32_t, uint8_t, const float*);
void DrawElementsInstanced(uint32_t, int32_t, uint32_t, intptr_t, int32_t);
uint32_t GetError();
}
}
namespace orbisfox {
namespace api = swgl_api;
void SwglCanvas::stop() {
    if (context) api::DestroyContext(context); // Owns the GL resources, not our external framebuffer.
    context = nullptr;
    free(bgra); bgra = nullptr;
    width = height = 0; program = vbo = vao = 0; transform = -1;
}
bool SwglCanvas::init(int w, int h) {
    stop();
    if (w < 64 || h < 64 || w > 4096 || h > 4096) return false;
    bgra = static_cast<uint8_t*>(malloc((size_t)w * h * 4 + 16));
    if (!bgra) return false;
    context = api::CreateContext();
    if (!context) { stop(); return false; }
    width = w; height = h;
    api::MakeCurrent(context);
    api::InitDefaultFramebuffer(0, 0, w, h, w * 4, bgra);
    program = api::CreateProgram();
    uint32_t vs = api::CreateShader(0x8B31), fs = api::CreateShader(0x8B30);
    char shader[] = "debug_color", position[] = "aPosition", color[] = "aColor", matrix[] = "uTransform";
    api::ShaderSourceByName(vs, shader); api::ShaderSourceByName(fs, shader);
    api::AttachShader(program, vs); api::AttachShader(program, fs);
    api::BindAttribLocation(program, 0, position); api::BindAttribLocation(program, 1, color);
    api::LinkProgram(program);
    api::DeleteShader(vs); api::DeleteShader(fs);
    if (!api::GetLinkStatus(program)) { stop(); return false; }
    transform = api::GetUniformLocation(program, matrix);
    api::GenBuffers(1, &vbo); api::GenVertexArrays(1, &vao);
    if (transform < 0 || !vbo || !vao || api::GetError() != 0) { stop(); return false; }
    return true;
}
bool SwglCanvas::render_shader_test(Surface dst) {
    if (!context || !valid(dst) || dst.width != width || dst.height != height) return false;
    api::MakeCurrent(context);
    api::SetViewport(0, 0, width, height);
    api::ClearColor(19.0f / 255, 27.0f / 255, 47.0f / 255, 1);
    api::Clear(0x00004000); // GL_COLOR_BUFFER_BIT
    api::UseProgram(program);
    const float w = (float)width, h = (float)height;
    // SWGL's framebuffer is top-left oriented. Map pixel positions to clip
    // space without an OpenGL-window y flip; host tests verify actual output.
    float matrix[] = {2 / w,0,0,0, 0,2 / h,0,0, 0,0,1,0, -1,-1,0,1};
    api::UniformMatrix4fv(transform, 1, 0, matrix);
    struct Vertex { float x, y, r, g, b, a; };
    Vertex vertices[] = {{w * .12f,h * .34f,1,0,0,1},
                         {w * .88f,h * .34f,0,1,0,1},
                         {w * .50f,h * .80f,0,0,1,1}};
    api::BindVertexArray(vao);
    api::BindBuffer(0x8892, vbo);
    api::BufferData(0x8892, sizeof(vertices), vertices, 0x88E4);
    api::VertexAttribPointer(0, 2, 0x1406, false, sizeof(Vertex), 0);
    api::VertexAttribPointer(1, 4, 0x1406, false, sizeof(Vertex), offsetof(Vertex, r));
    api::EnableVertexAttribArray(0); api::EnableVertexAttribArray(1);
    api::DrawElementsInstanced(4, 3, 0, 0, 1);
    if (api::GetError() != 0) return false;
    int32_t bw = 0, bh = 0, stride = 0;
    auto* source = static_cast<uint8_t*>(api::GetColorBuffer(0, 1, &bw, &bh, &stride));
    if (!source || bw != width || bh != height || stride < width * 4) return false;
    // SWGL RGBA8 backing is packed BGRA. Convert to our explicit RGBA surface.
    for (int y = 0; y < height; ++y)
        for (int x = 0; x < width; ++x) {
            const uint8_t* s = source + (size_t)y * stride + (size_t)x * 4;
            uint8_t* d = dst.pixels + (size_t)y * dst.stride + (size_t)x * 4;
            d[0] = s[2]; d[1] = s[1]; d[2] = s[0]; d[3] = s[3];
        }
    return true;
}
} // namespace orbisfox
