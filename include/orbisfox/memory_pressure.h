// SPDX-License-Identifier: MIT
#pragma once
#include <cstddef>
#include <cstdint>
namespace orbisfox {
// The flexible pool, not total PS4 RAM, bounds shared/file/stack mappings.
// Hysteresis and a cooldown avoid repeated stop-the-world collections.
class FlexibleMemoryPressure {
 public:
  enum class Event { None, Low, Recovered };
  Event sample(int result, size_t available, uint64_t now) {
    if (result != 0) return Event::None; // A failed query is not zero memory.
    if (pressured_ && available >= recoverBytes) {
      pressured_ = false; last_ = now; return Event::Recovered;
    }
    if (available < lowBytes && !pressured_) {
      pressured_ = true; last_ = now; return Event::Low;
    }
    if (pressured_ && now >= last_ && now - last_ >= repeatMicros) {
      last_ = now; return Event::Low;
    }
    return Event::None;
  }
  bool pressured() const { return pressured_; }
  static constexpr size_t lowBytes = 48u * 1024 * 1024;
  static constexpr size_t recoverBytes = 64u * 1024 * 1024;
  static constexpr uint64_t repeatMicros = 15000000;
 private:
  bool pressured_ = false;
  uint64_t last_ = 0;
};
} // namespace orbisfox
