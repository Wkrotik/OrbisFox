// SPDX-License-Identifier: MIT
#pragma once
#include <string.h>

namespace orbisfox {
// Identity is necessary but NOT sufficient: the production gate also creates an
// actual GLES 3 context, compiles/draws shaders, checks pixels and releases it.
inline bool IsOrbisMesaRenderer(const char *renderer) {
  return renderer && strstr(renderer, "zink") && strstr(renderer, "RADV ORBIS");
}
inline bool IsMesaProbePixel(const unsigned char *p) {
  return p && p[0] >= 62 && p[0] <= 66 && p[1] >= 126 && p[1] <= 130 &&
         p[2] >= 189 && p[2] <= 193 && p[3] == 255;
}
// Main-thread startup only, before XRE and any context-owning Gecko workers.
bool probe_native_mesa_gpu();
} // namespace orbisfox
