// Copyright OrbisFox contributors. Licensed under the ANGLE BSD-style license.
#include "system_utils.h"
#include <pthread.h>
#ifdef ORBISFOX_HOMEBREW_SDK
#include <pthread_np.h>
#endif
#include <time.h>

namespace angle {
std::string GetExecutablePath() { return "/app0/eboot.bin"; }
std::string GetExecutableDirectory() { return "/app0"; }
const char* GetSharedLibraryExtension() { return "so"; }
double GetCurrentSystemTime() {
  timespec value{};
  if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return 0;
  return value.tv_sec + value.tv_nsec * 1e-9;
}
void SetCurrentThreadName(const char* name) {
  if (name) pthread_set_name_np(pthread_self(), name);
}
}  // namespace angle
