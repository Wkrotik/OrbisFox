// SPDX-License-Identifier: MIT
#include "orbisfox/shared_memory_repro.h"
#ifdef __ORBIS__
#include "orbisfox/ps4_services.h"
#include "orbisfox/presenter.h"
#include <orbis/libkernel.h>
#include <stdarg.h>

namespace {
FILE* output = nullptr;
[[noreturn]] void finish() {
  if (output) { fflush(output); fclose(output); output = nullptr; }
  orbisfox::request_system_exit();
  // Do not return through the SDK's unsupported main/exit path if the
  // application manager is unavailable. Operator can close this title.
  for (;;) sceKernelUsleep(1000000);
}
}
namespace orbisfox {
void log(const char* format, ...) {
  va_list args; va_start(args, format); vfprintf(stdout, format, args); va_end(args);
  fputc('\n', stdout); fflush(stdout);
}
}
extern "C" {
using Init = void (*)();
extern Init __orbisfox_initializers_start[], __orbisfox_initializers_end[];
void shared_memory_probe_startup() {
  for (Init* p = __orbisfox_initializers_start; p != __orbisfox_initializers_end; ++p) (*p)();
}
}
asm(".pushsection .orbisfox.startup_entry,\"aw\",@init_array\n"
    ".p2align 3\n.quad shared_memory_probe_startup\n.popsection\n");
#endif

int main() {
#ifdef __ORBIS__
  // Dedicated diagnostic title; never reads/writes browser profiles or flags.
  // O_EXCL/O_NOFOLLOW + unique name preserve every prior probe run.
  const char* directory = "/data/orbisfox-shmem-probe";
  if (mkdir(directory, 0700) != 0 && errno != EEXIST) finish();
  struct stat st{};
  if (lstat(directory, &st) != 0 || !S_ISDIR(st.st_mode)) finish();
  char path[160];
  snprintf(path, sizeof(path), "%s/run-%d-%llu.log", directory, int(getpid()),
           (unsigned long long)sceKernelGetProcessTime());
  int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
  if (fd < 0) finish();
  output = fdopen(fd, "w");
  if (!output) { close(fd); finish(); }
  orbisfox::hide_splash_screen();
#else
  FILE* output = stdout;
#endif
  const bool ok = orbisfox::shm_repro::run(output);
  fprintf(output, "RESULT %s (native probe is not browser/GPU execution proof)\n", ok ? "PASS" : "FAIL");
  fflush(output);
#ifdef __ORBIS__
  finish();
#else
  return ok ? 0 : 1;
#endif
}
