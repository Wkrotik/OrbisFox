#pragma once
#include <stdint.h>
namespace orbisfox {
// Public OrbisPad button bits -> bounded host/UI protocol; no SDK ABI objects.
constexpr uint32_t browser_buttons(uint32_t raw, bool shell) {
  uint32_t result = ((raw & 0x4000) ? 1u : 0u) | ((raw & 0x1000) ? 2u : 0u) |
                    ((raw & 0x8000) ? 4u : 0u);
  if (shell) result |= ((raw & 0x0008) ? 8u : 0u) | ((raw & 0x2000) ? 16u : 0u) |
    ((raw & 0x0080) ? 32u : 0u) | ((raw & 0x0020) ? 64u : 0u) |
    ((raw & 0x0010) ? 128u : 0u) | ((raw & 0x0040) ? 256u : 0u) |
    ((raw & 0x0400) ? 512u : 0u) | ((raw & 0x0800) ? 1024u : 0u) |
    ((raw & 0x0200) ? 2048u : 0u) | ((raw & 0x0100) ? 4096u : 0u) |
    ((raw & 0x0004) ? 8192u : 0u) | ((raw & 0x0002) ? 16384u : 0u);
  return result;
}
constexpr bool browser_exit_chord(uint32_t raw, bool shell) {
  return (raw & 0x0008) && (!shell || (raw & 0x2000));
}
}
