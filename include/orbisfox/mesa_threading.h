// SPDX-License-Identifier: MIT
#pragma once
#include <string.h>

namespace orbisfox {
// Experimental Orbis stability policy, applied before the FIRST EGL context.
// WebRender already submits GL on its render thread. Do not add Mesa's optional
// CPU-side GL marshalling worker until its behavior is validated on this port.
// This does NOT disable Zink/RADV, shader compilation, GPU fences or WebRender.
// A successful setter alone is insufficient: verify the value is visible.
// Does not claim that glthread is the source of the observed heap corruption.
template<class SetEnvironment, class GetEnvironment>
bool configure_mesa_render_thread_policy(SetEnvironment set, GetEnvironment get) {
  if (set("mesa_glthread", "false", 1) != 0) return false;
  const char* value = get("mesa_glthread");
  return value && strcmp(value, "false") == 0;
}
} // namespace orbisfox
