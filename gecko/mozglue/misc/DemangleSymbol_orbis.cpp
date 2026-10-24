/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "StackWalk.h"
#include <cxxabi.h>
#include <cstdlib>
#include <cstring>

// On Orbis, upstream StackWalk.cpp provides this API when both dladdr and
// _Unwind_Backtrace are available. Keep only the missing-provider fallback.
#if !(defined(HAVE_DLADDR) && HAVE_DLADDR && \
      defined(HAVE__UNWIND_BACKTRACE) && HAVE__UNWIND_BACKTRACE)
namespace mozilla {
void DemangleSymbol(const char* aSymbol, char* aBuffer, int aBufLen) {
  if (!aBuffer || aBufLen <= 0) return;
  aBuffer[0] = '\0';
  if (!aSymbol) return;
  int status = -1;
  char* result = abi::__cxa_demangle(aSymbol, nullptr, nullptr, &status);
  if (result && status == 0) {
    std::strncpy(aBuffer, result, static_cast<size_t>(aBufLen));
    aBuffer[aBufLen - 1] = '\0';
  }
  std::free(result);
}
}  // namespace mozilla
#endif
