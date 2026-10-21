#include "orbisfox/native_stat.h"
#include "orbisfox/presenter.h"
#include <atomic>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>
#ifndef ORBISFOX_HOMEBREW_SDK
#include <orbis/libkernel.h>
namespace {
using PathStat = int (*)(const char*, orbisfox::FirmwareStat*);
using FdStat = int (*)(int, orbisfox::FirmwareStat*);
PathStat nativeStat = nullptr, nativeLstat = nullptr;
FdStat nativeFstat = nullptr;
constinit std::atomic<int> binding{0};
bool symbol(OrbisKernelModule module, const char* name, void** address) {
    if (sceKernelDlsym(module, name, address) < 0 || !*address) return false;
    void *low = nullptr, *high = nullptr; int32_t protection = 0;
    return sceKernelQueryMemoryProtection(*address, &low, &high, &protection) == 0
        && (protection & ORBIS_KERNEL_PROT_CPU_EXEC)
        && reinterpret_cast<uintptr_t>(*address) >= reinterpret_cast<uintptr_t>(low)
        && reinterpret_cast<uintptr_t>(*address) < reinterpret_cast<uintptr_t>(high);
}
bool bind() {
    int state = binding.load(std::memory_order_acquire);
    if (state == 2) return true;
    if (state == -1) return false;
    int expected = 0;
    if (binding.compare_exchange_strong(expected, 1, std::memory_order_acq_rel)) {
        bool found = false;
        OrbisKernelModule modules[256]{}; size_t count = 0;
        if (sceKernelGetModuleList(modules, 256, &count) == 0 && count <= 256) {
            for (size_t i = 0; i < count; ++i) {
                OrbisKernelModuleInfo info{}; info.size = sizeof(info);
                if (sceKernelGetModuleInfo(modules[i], &info) != 0 ||
                    !memchr(info.name, 0, sizeof(info.name))) continue;
                const char* name = strrchr(info.name, '/'); name = name ? name + 1 : info.name;
                if (strncmp(name, "libkernel", 9) != 0) continue;
                void *s = nullptr, *l = nullptr, *f = nullptr;
                if (!symbol(modules[i], "stat", &s) || !symbol(modules[i], "lstat", &l)
                    || !symbol(modules[i], "fstat", &f)) continue;
                nativeStat = reinterpret_cast<PathStat>(s);
                nativeLstat = reinterpret_cast<PathStat>(l);
                nativeFstat = reinterpret_cast<FdStat>(f);
                found = true; break;
            }
        }
        binding.store(found ? 2 : -1, std::memory_order_release);
        return found;
    }
    while ((state = binding.load(std::memory_order_acquire)) == 1) __asm__ volatile("pause");
    return state == 2;
}
struct GuardedStat {
    unsigned char before[32];
    orbisfox::FirmwareStat value;
    // Room for an unexpected larger firmware record; reject any such write
    // without letting it reach the stack canary or caller's SDK record.
    unsigned char surplus[256 - sizeof(orbisfox::FirmwareStat)];
    unsigned char after[32];
    GuardedStat() { memset(this, 0xa5, sizeof(*this)); }
    bool intact() const {
        for (auto byte : before) if (byte != 0xa5) return false;
        for (auto byte : surplus) if (byte != 0xa5) return false;
        for (auto byte : after) if (byte != 0xa5) return false;
        return true;
    }
};
int finish(int result, GuardedStat& native, struct stat* output) {
    if (!native.intact()) { errno = EOVERFLOW; return -1; }
    if (result != 0) return result;
    orbisfox::translate_stat(native.value, *output);
    return 0;
}
}
// SDK/Rust-facing record remains unchanged. Marshal actual firmware results
// instead of exposing Linux fstatat stubs or misreading the BSD packed record.
extern "C" int stat(const char* path, struct stat* output) {
    if (!output || !path) { errno = EFAULT; return -1; }
    if (!bind()) { errno = ENOSYS; return -1; }
    GuardedStat native;
    return finish(nativeStat(path, &native.value), native, output);
}
extern "C" int lstat(const char* path, struct stat* output) {
    if (!output || !path) { errno = EFAULT; return -1; }
    if (!bind()) { errno = ENOSYS; return -1; }
    GuardedStat native;
    return finish(nativeLstat(path, &native.value), native, output);
}
extern "C" int fstat(int fd, struct stat* output) {
    if (!output) { errno = EFAULT; return -1; }
    if (!bind()) { errno = ENOSYS; return -1; }
    GuardedStat native;
    return finish(nativeFstat(fd, &native.value), native, output);
}
#endif // Only the musl-facing SDK requires global stat interposition.
namespace orbisfox {
namespace {
struct ProbeStatGuard {
    unsigned char before[32];
    struct stat value;
    unsigned char surplus[128], after[32];
    ProbeStatGuard() { memset(this, 0xa5, sizeof(*this)); value = {}; }
    bool intact() const {
        for (auto byte : before) if (byte != 0xa5) return false;
        for (auto byte : surplus) if (byte != 0xa5) return false;
        for (auto byte : after) if (byte != 0xa5) return false;
        return true;
    }
};
}
bool probe_native_filesystem_metadata() {
#ifdef ORBISFOX_HOMEBREW_SDK
    static_assert(sizeof(struct stat) == sizeof(FirmwareStat));
    static_assert(offsetof(struct stat, st_atim) == offsetof(FirmwareStat, accessed));
    static_assert(offsetof(struct stat, st_size) == offsetof(FirmwareStat, bytes));
    static_assert(offsetof(struct stat, st_birthtim) == offsetof(FirmwareStat, created));
    log("Filesystem native SDK stat/lstat/fstat: direct imports; no musl record translation");
#else
    log("Filesystem firmware binding: %s", bind() ? "PASS" : "FAIL");
#endif
    ProbeStatGuard pathRecord, linkRecord, descriptorRecord, directoryRecord;
    auto& path = pathRecord.value;
    auto& link = linkRecord.value;
    auto& descriptor = descriptorRecord.value;
    auto& directory = directoryRecord.value;
    const char* font = "/app0/assets/fonts/NotoSans-Regular.ttf";
    const int a = stat(font, &path), b = lstat(font, &link);
    const int fd = open(font, O_RDONLY);
    const int c = fd >= 0 ? fstat(fd, &descriptor) : -1;
    if (fd >= 0) close(fd);
    const int d = stat("/app0/gecko", &directory);
    const bool guards = pathRecord.intact() && linkRecord.intact()
        && descriptorRecord.intact() && directoryRecord.intact();
    const bool ok = guards && a == 0 && b == 0 && c == 0 && d == 0
        && path.st_size == 569208 && link.st_size == path.st_size
        && descriptor.st_size == path.st_size && descriptor.st_ino == path.st_ino
        && S_ISREG(path.st_mode) && S_ISREG(link.st_mode) && S_ISREG(descriptor.st_mode)
        && S_ISDIR(directory.st_mode);
    log("Filesystem guarded stat/lstat/fstat: %s status=%d/%d/%d/%d font=%lld/%lld/%lld directory-mode=0x%x",
        ok ? "PASS" : "FAIL", a,b,c,d, (long long)path.st_size, (long long)link.st_size,
        (long long)descriptor.st_size, unsigned(directory.st_mode));
    return ok;
}
}
