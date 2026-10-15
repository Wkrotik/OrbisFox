#include "orbisfox/native_cpu.h"
#include <cerrno>
#include <cstdint>
#include <unistd.h>

// Typed aliases isolate this native ABI boundary from the public toolchain's
// void-return Getaffinity declaration. Orbis threads are opaque handles, and
// the actual kernel affinity API writes a 64-bit mask and returns an error code.
extern "C" void* native_cpu_thread_self() __asm__("scePthreadSelf");
extern "C" int native_cpu_thread_affinity(void*, std::uint64_t*) __asm__("scePthreadGetaffinity");
extern "C" long __real_sysconf(int name);

namespace orbisfox {
int native_available_processor_count() {
  const int saved = errno;
  std::uint64_t mask = 0;
  void* thread = native_cpu_thread_self();
  const int result = thread ? native_cpu_thread_affinity(thread, &mask) : -1;
  errno = saved;
  if (result != 0 || mask == 0) return 0;
  return __builtin_popcountll(mask);
}
}

extern "C" long __wrap_sysconf(int name) {
  // No changes to page sizes, limits, memory information or other SDK queries.
  // The SDK's processor branch uses a different affinity ABI and ignores its
  // result. NSPR/Gecko consequently can size decoder/helper pools as one core.
  if (name == _SC_NPROCESSORS_CONF || name == _SC_NPROCESSORS_ONLN) {
    const int count = orbisfox::native_available_processor_count();
    if (count > 0) return count;
  }
  return __real_sysconf(name);
}
