// Log static initialization before main using only firmware file APIs. No
// stdio, allocation, TLS, C++ streams, or Gecko calls are required by tracing.
#include <orbis/libkernel.h>
#include "orbisfox/run_logs.h"
#include <fcntl.h>
#include <stdint.h>
#include <stddef.h>

#ifndef ORBISFOX_HOMEBREW_SDK
extern "C" {
using Initializer = void (*)();
extern Initializer __orbisfox_initializers_start[];
extern Initializer __orbisfox_initializers_end[];
extern const unsigned char __text_start[];
}
#endif
namespace {
void write_all(int fd, const char* data, size_t size) {
    while (fd >= 0 && size) {
        // The SDK declares size_t, but kernel errors are negative signed values.
        const intptr_t count = static_cast<intptr_t>(sceKernelWrite(fd, data, size));
        if (count <= 0 || static_cast<size_t>(count) > size) return;
        data += count; size -= static_cast<size_t>(count);
    }
}
void mark(int fd, const char* stage, uintptr_t address) {
    char line[96]; size_t n = 0;
    while (*stage && n < 65) line[n++] = *stage++;
    line[n++] = ' '; line[n++] = '0'; line[n++] = 'x';
    constexpr char digits[] = "0123456789abcdef";
    for (int shift = 60; shift >= 0; shift -= 4) line[n++] = digits[(address >> shift) & 15];
    line[n++] = '\n';
    write_all(fd, line, n);
}
} // namespace
extern "C" void orbisfox_startup_dispatch() {
    sceKernelMkdir("/data/orbisfox", 0700);
#ifdef ORBISFOX_FULL_GECKO
    if(!orbisfox::initialize_native_run_logs()){
        static const char error[]="OrbisFox run-log initialization failed; refusing to overwrite earlier logs\n";
        sceKernelWrite(2,error,sizeof(error)-1);
    }
    const int fd = orbisfox::native_diagnostics_enabled() ? sceKernelOpen(orbisfox::NativeRunLogPath("startup-layout.log").c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600) : -1;
#ifdef ORBISFOX_HOMEBREW_SDK
    constexpr char banner[] = "OrbisFox 0.68 native SDK preinit; CRT owns constructors\n";
#else
    constexpr char banner[] = "OrbisFox 0.68 static initialization diagnostics\n";
#endif
#else
    const int fd = sceKernelOpen("/data/orbisfox/startup.log", O_WRONLY | O_CREAT | O_TRUNC, 0600);
    constexpr char banner[] = "OrbisFox 0.11 pre-main static initializer trace\n";
#endif
    write_all(fd, banner, sizeof(banner) - 1);
#ifdef ORBISFOX_HOMEBREW_SDK
    // The real SDK _init invokes .preinit_array after libc's _init_env and
    // before its own .init_array loop. Do not relocate, run twice, or claim
    // completion of constructors that the CRT has not invoked yet.
    mark(fd, "NATIVE SDK PREINIT ENTRY", reinterpret_cast<uintptr_t>(&orbisfox_startup_dispatch));
    constexpr char done[] = "NATIVE SDK PREINIT COMPLETED; CONSTRUCTORS STILL OWNED BY CRT\n";
#else
    mark(fd, "IMAGE BASE", reinterpret_cast<uintptr_t>(__text_start));
    for (Initializer* entry = __orbisfox_initializers_start; entry != __orbisfox_initializers_end; ++entry) {
        const uintptr_t offset = reinterpret_cast<uintptr_t>(*entry) - reinterpret_cast<uintptr_t>(__text_start);
        mark(fd, "INITIALIZER BEGIN ELF OFFSET", offset);
        (*entry)();
        mark(fd, "INITIALIZER END ELF OFFSET", offset);
    }
    constexpr char done[] = "ALL STATIC INITIALIZERS COMPLETED\n";
#endif
    write_all(fd, done, sizeof(done) - 1);
    if (fd >= 0) sceKernelClose(fd);
}
#ifdef ORBISFOX_HOMEBREW_SDK
// Use the SDK's genuine ELF startup facility. Its normal constructor table and
// runtime registrations remain intact; the old custom linker is not required.
asm(".pushsection .preinit_array,\"aw\",@preinit_array\n"
    ".p2align 3\n"
    ".quad orbisfox_startup_dispatch\n"
    ".popsection\n");
#else
// The linker installs this as the sole DT_INIT_ARRAY entry and moves all
// upstream entries into a separately rooted, priority-sorted dispatch table.
asm(".pushsection .orbisfox.startup_entry,\"aw\",@init_array\n"
    ".p2align 3\n"
    ".quad orbisfox_startup_dispatch\n"
    ".popsection\n");
#endif
