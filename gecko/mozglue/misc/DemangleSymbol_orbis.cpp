/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */
#include "StackWalk.h"
#include <cxxabi.h>
#include <cstdlib>
#include <cstring>

// The unsupported native stack-walk branch does not define this shared API.
// Keep genuine private-libc++abi demangling independently of stack sampling.
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
