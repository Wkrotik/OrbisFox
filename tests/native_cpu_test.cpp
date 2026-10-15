#include "orbisfox/native_cpu.h"
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <unistd.h>

extern "C" long sdk_sysconf(int);
extern "C" long __wrap_sysconf(int);
namespace {
std::uint64_t mask = 0x3f;
int nativeResult = 0, sdkCalls = 0, nativeCalls = 0;
bool threadPresent = true, sdkAffinityAvailable = false;
}
extern "C" void* scePthreadSelf() { return threadPresent ? &mask : nullptr; }
extern "C" int scePthreadGetaffinity(void* thread, std::uint64_t* out) {
  assert(thread == &mask); ++nativeCalls;
  *out = mask;
  return nativeResult;
}
// Exact unmodified SDK sysconf object, with only its entry name isolated.
// Supply its firmware imports, not replacement sysconf logic.
extern "C" int cpuset_getaffinity(int level, int which, std::int64_t id,
                                   std::size_t bytes, void* out) {
  assert(level == 0 && which == 0 && id == 0 && bytes == 128);
  if (!sdkAffinityAvailable) { errno = EINVAL; return -1; }
  std::memset(out, 0, bytes); std::memcpy(out, &mask, sizeof(mask)); return 0;
}
extern "C" int* ___errno_location() { return &errno; }
extern "C" int __lsysinfo(void*) { assert(false); return -1; }
extern "C" std::uint64_t sceKernelGetDirectMemorySize() { assert(false); return 0; }
extern "C" long __real_sysconf(int name) { ++sdkCalls; return sdk_sysconf(name); }

int main() {
  // SDK CPU path ignores affinity-query failure and returns its seed mask's
  // count (one), even when the native API genuinely makes six cores available.
  assert(sdk_sysconf(83) == 1 && sdk_sysconf(84) == 1);
  sdkAffinityAvailable = true;
  assert(sdk_sysconf(83) == 6 && sdk_sysconf(84) == 6);
  for (std::uint64_t value : {std::uint64_t(1), std::uint64_t(0x3f), std::uint64_t(0x7f), std::uint64_t(1) << 63}) {
    mask = value; errno = EBUSY;
    const auto count = __builtin_popcountll(mask);
    assert(orbisfox::native_available_processor_count() == count);
    assert(__wrap_sysconf(_SC_NPROCESSORS_CONF) == count);
    assert(__wrap_sysconf(_SC_NPROCESSORS_ONLN) == count);
    assert(errno == EBUSY && sdkCalls == 0);
  }
  const int before = nativeCalls;
  assert(__wrap_sysconf(_SC_PAGESIZE) == sdk_sysconf(_SC_PAGESIZE));
  assert(nativeCalls == before && sdkCalls == 1);
  errno = 0; assert(__wrap_sysconf(-1) == -1 && errno == EINVAL);
  assert(nativeCalls == before && sdkCalls == 2);
  mask = 0; assert(orbisfox::native_available_processor_count() == 0);
  assert(__wrap_sysconf(_SC_NPROCESSORS_ONLN) == sdk_sysconf(_SC_NPROCESSORS_ONLN));
  mask = 0x3f; nativeResult = 73;
  assert(orbisfox::native_available_processor_count() == 0);
  assert(__wrap_sysconf(_SC_NPROCESSORS_ONLN) == sdk_sysconf(_SC_NPROCESSORS_ONLN));
  nativeResult = 0; threadPresent = false;
  assert(orbisfox::native_available_processor_count() == 0);
  std::puts("Actual SDK sysconf CPU bug reproduced; genuine-mask adapter, errors/zero and unrelated SDK queries preserved. Host doubles, not firmware proof.");
}
