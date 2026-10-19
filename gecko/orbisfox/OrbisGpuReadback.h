/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#ifndef OrbisGpuReadback_h
#define OrbisGpuReadback_h
#include <limits>
#include <stddef.h>
#include <stdint.h>

namespace orbisfox {
// GL's lower-left RGBA rows -> native mailbox's upper-left BGRA rows. Buffers
// must be distinct; padding is untouched. Validate everything before writing.
inline bool ConvertGpuRgbaToBgra(const uint8_t *source, size_t sourceBytes,
                                 size_t sourceStride, uint8_t *destination,
                                 size_t destinationBytes,
                                 size_t destinationStride, uint32_t width,
                                 uint32_t height) {
  if (!source || !destination || !width || !height || width > 1280 ||
      height > 720)
    return false;
  const size_t rowBytes = size_t(width) * 4;
  const auto span = [=](size_t stride, size_t bytes, size_t *used) {
    if (stride < rowBytes ||
        (height > 1 &&
         stride >
             (std::numeric_limits<size_t>::max() - rowBytes) / (height - 1)))
      return false;
    *used = size_t(height - 1) * stride + rowBytes;
    return bytes >= *used;
  };
  size_t sourceUsed, destinationUsed;
  if (!span(sourceStride, sourceBytes, &sourceUsed) ||
      !span(destinationStride, destinationBytes, &destinationUsed))
    return false;
  const uintptr_t s = reinterpret_cast<uintptr_t>(source);
  const uintptr_t d = reinterpret_cast<uintptr_t>(destination);
  if ((s <= d && d - s < sourceUsed) || (d < s && s - d < destinationUsed))
    return false;
  for (uint32_t y = 0; y < height; ++y) {
    const uint8_t *input = source + size_t(height - 1 - y) * sourceStride;
    uint8_t *output = destination + size_t(y) * destinationStride;
    for (uint32_t x = 0; x < width; ++x) {
      output[x * 4] = input[x * 4 + 2];
      output[x * 4 + 1] = input[x * 4 + 1];
      output[x * 4 + 2] = input[x * 4];
      output[x * 4 + 3] = input[x * 4 + 3];
    }
  }
  return true;
}
} // namespace orbisfox
#endif
