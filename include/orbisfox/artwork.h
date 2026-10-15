#pragma once
#include "orbisfox/surface.h"
namespace orbisfox {
// Build-time decoded RGBA artwork, with an exact-size little-endian header.
// No runtime image codec is needed during application startup.
bool load_artwork(const char* path, Surface destination);
}
