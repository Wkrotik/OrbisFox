/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "ProcInfo.h"
#include <time.h>
#include <limits>

namespace mozilla {
nsresult GetCurrentProcessMemoryUsage(uint64_t* aResult) {
  NS_ENSURE_ARG_POINTER(aResult);
  *aResult = 0;
  return NS_ERROR_NOT_AVAILABLE;
}
nsresult GetGpuTimeSinceProcessStartInMs(uint64_t* aResult) {
  NS_ENSURE_ARG_POINTER(aResult);
  *aResult = 0;
  return NS_ERROR_NOT_AVAILABLE;
}
nsresult GetCpuTimeSinceProcessStartInMs(uint64_t* aResult) {
  NS_ENSURE_ARG_POINTER(aResult);
  *aResult = 0;
  timespec time{};
  if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &time) != 0 || time.tv_sec < 0 ||
      time.tv_nsec < 0 || time.tv_nsec >= 1000000000) {
    return NS_ERROR_NOT_AVAILABLE;
  }
  const uint64_t millis = static_cast<uint64_t>(time.tv_nsec) / 1000000;
  if (static_cast<uint64_t>(time.tv_sec) >
      (std::numeric_limits<uint64_t>::max() - millis) / 1000) {
    return NS_ERROR_FAILURE;
  }
  *aResult = static_cast<uint64_t>(time.tv_sec) * 1000 + millis;
  return NS_OK;
}
ProcInfoPromise::ResolveOrRejectValue GetProcInfoSync(
    nsTArray<ProcInfoRequest>&&) {
  ProcInfoPromise::ResolveOrRejectValue result;
  result.SetReject(NS_ERROR_NOT_IMPLEMENTED);
  return result;
}
}  // namespace mozilla
