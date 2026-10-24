// SPDX-License-Identifier: MIT
// Native link/ABI fixture only. Do not package or execute as a console app.
#include "orbisfox/presenter.h"
#include "orbisfox/rust_runtime.h"
#include <cstdarg>
#include <cstdio>
namespace orbisfox {
void log(const char* format, ...) {
  va_list args;
  va_start(args, format);
  vfprintf(stderr, format, args);
  va_end(args);
}
}  // namespace orbisfox
extern "C" unsigned orbisfox_rust_native_threads_probe();
int main() {
  return orbisfox::probe_rust_runtime() &&
                 orbisfox_rust_native_threads_probe() == 1 ? 0 : 1;
}
