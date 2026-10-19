// SPDX-License-Identifier: MIT
// A real GLES operation gate, before XRE/worker creation. No CPU
// executable-memory allocation, VideoOut ownership, substituted GL
// implementation, or claimed HW decode.
#include "orbisfox/mesa_probe.h"
#include "orbisfox/presenter.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <string.h>

extern "C" bool orbis_mesa_native_ready();
static bool gpu_ready = false;
static bool probe_attempted = false;
extern "C" bool orbis_mesa_gpu_ready() { return gpu_ready; }

namespace orbisfox {
namespace {
struct GL {
#define PROC(name) decltype(&gl##name) name = nullptr;
  PROC(GetString)
  PROC(GetIntegerv) PROC(GetError) PROC(CreateShader) PROC(ShaderSource)
      PROC(CompileShader) PROC(GetShaderiv) PROC(GetShaderInfoLog)
          PROC(DeleteShader) PROC(CreateProgram) PROC(AttachShader)
              PROC(LinkProgram) PROC(GetProgramiv) PROC(GetProgramInfoLog)
                  PROC(DeleteProgram) PROC(UseProgram) PROC(Viewport)
                      PROC(DrawArrays) PROC(PixelStorei) PROC(ReadPixels)
                          PROC(Finish)
#undef PROC
                              bool load() {
#define LOAD(name)                                                             \
  name = reinterpret_cast<decltype(name)>(eglGetProcAddress("gl" #name));      \
  if (!name)                                                                   \
    return false;
    LOAD(GetString)
    LOAD(GetIntegerv) LOAD(GetError) LOAD(CreateShader) LOAD(ShaderSource)
        LOAD(CompileShader) LOAD(GetShaderiv) LOAD(GetShaderInfoLog)
            LOAD(DeleteShader) LOAD(CreateProgram) LOAD(AttachShader)
                LOAD(LinkProgram) LOAD(GetProgramiv) LOAD(GetProgramInfoLog)
                    LOAD(DeleteProgram) LOAD(UseProgram) LOAD(Viewport)
                        LOAD(DrawArrays) LOAD(PixelStorei) LOAD(ReadPixels)
                            LOAD(Finish)
#undef LOAD
                                return true;
  }
};
GLuint compile(GL &gl, GLenum type, const char *source) {
  GLuint shader = gl.CreateShader(type);
  if (!shader)
    return 0;
  gl.ShaderSource(shader, 1, &source, nullptr);
  gl.CompileShader(shader);
  GLint compiled = 0;
  gl.GetShaderiv(shader, GL_COMPILE_STATUS, &compiled);
  if (!compiled) {
    char reason[192]{};
    gl.GetShaderInfoLog(shader, sizeof(reason) - 1, nullptr, reason);
    log("Experimental Mesa: real shader compile failed: %.191s", reason);
    gl.DeleteShader(shader);
    return 0;
  }
  return shader;
}
bool render(GL &gl) {
  GLint major = 0;
  gl.GetIntegerv(GL_MAJOR_VERSION, &major);
  const auto *renderer =
      reinterpret_cast<const char *>(gl.GetString(GL_RENDERER));
  const auto *version =
      reinterpret_cast<const char *>(gl.GetString(GL_VERSION));
  log("Experimental Mesa: actual GL renderer=%.255s version=%.127s",
      renderer ? renderer : "unavailable", version ? version : "unavailable");
  if (major < 3 || !IsOrbisMesaRenderer(renderer) ||
      gl.GetError() != GL_NO_ERROR)
    return false;
  static const char *vertex =
      "#version 300 es\nvoid main(){vec2 "
      "p=gl_VertexID==0?vec2(-1.,-1.):gl_VertexID==1?vec2(3.,-1.):vec2(-1.,3.);"
      "gl_Position=vec4(p,0.,1.);}";
  static const char *fragment =
      "#version 300 es\nprecision highp float;out vec4 color;void "
      "main(){color=vec4(0.25,0.5,0.75,1.);}";
  const GLuint vs = compile(gl, GL_VERTEX_SHADER, vertex);
  const GLuint fs = compile(gl, GL_FRAGMENT_SHADER, fragment);
  GLuint program = vs && fs ? gl.CreateProgram() : 0;
  bool passed = false;
  if (program) {
    gl.AttachShader(program, vs);
    gl.AttachShader(program, fs);
    gl.LinkProgram(program);
    GLint linked = 0;
    gl.GetProgramiv(program, GL_LINK_STATUS, &linked);
    if (linked) {
      gl.UseProgram(program);
      gl.Viewport(0, 0, 8, 8);
      gl.DrawArrays(GL_TRIANGLES, 0, 3);
      gl.Finish();
      unsigned char pixel[4]{};
      gl.PixelStorei(GL_PACK_ALIGNMENT, 1);
      gl.ReadPixels(4, 4, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
      passed = gl.GetError() == GL_NO_ERROR && IsMesaProbePixel(pixel);
      log("Experimental Mesa: actual shader readback %u,%u,%u,%u passed=%d",
          pixel[0], pixel[1], pixel[2], pixel[3], passed);
    } else {
      char reason[192]{};
      gl.GetProgramInfoLog(program, sizeof(reason) - 1, nullptr, reason);
      log("Experimental Mesa: real shader link failed: %.191s", reason);
    }
    gl.UseProgram(0);
    gl.DeleteProgram(program);
  }
  if (vs)
    gl.DeleteShader(vs);
  if (fs)
    gl.DeleteShader(fs);
  return passed && gl.GetError() == GL_NO_ERROR;
}
} // namespace

bool probe_native_mesa_gpu() {
  // Called once on main, not a repeated probe while Gecko owns any context.
  if (probe_attempted)
    return gpu_ready;
  probe_attempted = true;
  if (!orbis_mesa_native_ready())
    return false;
  EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
  if (display == EGL_NO_DISPLAY)
    return false;
  EGLint major = 0, minor = 0;
  if (!eglInitialize(display, &major, &minor)) {
    log("Experimental Mesa: actual eglInitialize failed 0x%x", eglGetError());
    return false;
  }
  EGLSurface surface = EGL_NO_SURFACE;
  EGLContext context = EGL_NO_CONTEXT;
  bool current = false, passed = false;
  const EGLint configAttributes[] = {EGL_SURFACE_TYPE,
                                     EGL_PBUFFER_BIT,
                                     EGL_RENDERABLE_TYPE,
                                     EGL_OPENGL_ES3_BIT_KHR,
                                     EGL_RED_SIZE,
                                     8,
                                     EGL_GREEN_SIZE,
                                     8,
                                     EGL_BLUE_SIZE,
                                     8,
                                     EGL_ALPHA_SIZE,
                                     8,
                                     EGL_NONE};
  EGLConfig config{};
  EGLint count = 0;
  if (eglBindAPI(EGL_OPENGL_ES_API) &&
      eglChooseConfig(display, configAttributes, &config, 1, &count) &&
      count == 1) {
    const EGLint surfaceAttributes[] = {EGL_WIDTH, 8, EGL_HEIGHT, 8, EGL_NONE};
    surface = eglCreatePbufferSurface(display, config, surfaceAttributes);
    const EGLint contextAttributes[] = {EGL_CONTEXT_CLIENT_VERSION, 3,
                                        EGL_NONE};
    if (surface != EGL_NO_SURFACE)
      context =
          eglCreateContext(display, config, EGL_NO_CONTEXT, contextAttributes);
    if (context != EGL_NO_CONTEXT &&
        eglMakeCurrent(display, surface, surface, context)) {
      current = true;
      GL gl;
      passed = gl.load() && render(gl);
    }
  }
  if (!passed)
    log("Experimental Mesa: GPU operation gate failed, EGL error=0x%x",
        eglGetError());
  if (current && !eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE,
                                 EGL_NO_CONTEXT)) {
    // Ownership uncertain: do not guess a release. EGL entry stays disabled;
    // software rendering can proceed without calling Mesa. Process exit owns
    // cleanup.
    log("Experimental Mesa: detach failed; retaining failed probe resources, "
        "GPU disabled");
    return false;
  }
  bool cleaned = true;
  if (context != EGL_NO_CONTEXT && !eglDestroyContext(display, context))
    cleaned = false;
  if (surface != EGL_NO_SURFACE && !eglDestroySurface(display, surface))
    cleaned = false;
  if (!eglTerminate(display))
    cleaned = false;
  gpu_ready = passed && cleaned;
  log("Experimental Mesa: operation gate %s; browser hardware frames not yet "
      "confirmed",
      gpu_ready ? "passed" : "unavailable");
  return gpu_ready;
}
} // namespace orbisfox
