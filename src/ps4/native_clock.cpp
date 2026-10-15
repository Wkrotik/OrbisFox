#ifdef ORBISFOX_FULL_GECKO
#include "orbisfox/native_clock.h"
#include <atomic>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <pthread.h>
#include <orbis/libkernel.h>
namespace {
using ReadClock = int (*)(int, struct timespec*);
using SetConditionClock = int (*)(pthread_condattr_t*, int);
using GetConditionClock = int (*)(const pthread_condattr_t*, int*);
ReadClock nativeGetTime = nullptr, nativeGetRes = nullptr;
SetConditionClock nativeSetConditionClock = nullptr;
GetConditionClock nativeGetConditionClock = nullptr;
constinit std::atomic<int> clockBinding{0};
bool clockSymbol(OrbisKernelModule module, const char* name, void** address) {
    if (sceKernelDlsym(module, name, address) < 0 || !*address) return false;
    void *low = nullptr, *high = nullptr; int32_t protection = 0;
    return sceKernelQueryMemoryProtection(*address, &low, &high, &protection) == 0
        && (protection & ORBIS_KERNEL_PROT_CPU_EXEC)
        && reinterpret_cast<uintptr_t>(*address) >= reinterpret_cast<uintptr_t>(low)
        && reinterpret_cast<uintptr_t>(*address) < reinterpret_cast<uintptr_t>(high);
}
bool bindClocks() {
    int state = clockBinding.load(std::memory_order_acquire);
    if (state == 2) return true;
    if (state == -1) return false;
    int expected = 0;
    if (clockBinding.compare_exchange_strong(expected, 1, std::memory_order_acq_rel)) {
        bool found = false;
        OrbisKernelModule modules[256]{}; size_t count = 0;
        if (sceKernelGetModuleList(modules, 256, &count) == 0 && count <= 256) {
            for (size_t i = 0; i < count; ++i) {
                OrbisKernelModuleInfo info{}; info.size = sizeof(info);
                if (sceKernelGetModuleInfo(modules[i], &info) != 0 ||
                    !memchr(info.name, 0, sizeof(info.name))) continue;
                const char* name = strrchr(info.name, '/'); name = name ? name + 1 : info.name;
                if (strncmp(name, "libkernel", 9) != 0) continue;
                void *time = nullptr, *res = nullptr, *set = nullptr, *get = nullptr;
                if (!clockSymbol(modules[i], "clock_gettime", &time) ||
                    !clockSymbol(modules[i], "clock_getres", &res) ||
                    !clockSymbol(modules[i], "pthread_condattr_setclock", &set)) continue;
                // Getter is probe-only; its absence must not invalidate the
                // required clocks during pre-main timestamp initialization.
                if (!clockSymbol(modules[i], "pthread_condattr_getclock", &get)) get = nullptr;
                nativeGetTime = reinterpret_cast<ReadClock>(time);
                nativeGetRes = reinterpret_cast<ReadClock>(res);
                nativeSetConditionClock = reinterpret_cast<SetConditionClock>(set);
                nativeGetConditionClock = reinterpret_cast<GetConditionClock>(get);
                found = true; break;
            }
        }
        clockBinding.store(found ? 2 : -1, std::memory_order_release);
        return found;
    }
    while ((state = clockBinding.load(std::memory_order_acquire)) == 1) __asm__ volatile("pause");
    return state == 2;
}
struct GuardedClock {
    unsigned char before[32];
    timespec value;
    unsigned char surplus[64], after[32];
    GuardedClock() { memset(this, 0xa5, sizeof(*this)); }
    bool intact() const {
        for (auto c : before) if (c != 0xa5) return false;
        for (auto c : surplus) if (c != 0xa5) return false;
        for (auto c : after) if (c != 0xa5) return false;
        return true;
    }
};
int readClock(ReadClock function, int nativeId, timespec* output) {
    GuardedClock record;
    int result = function(nativeId, &record.value);
    if (!record.intact()) { errno = EOVERFLOW; return -1; }
    if (result != 0) return result; // Preserve native POSIX error/errno, no synthetic time.
    if (record.value.tv_nsec < 0 || record.value.tv_nsec >= 1000000000) {
        errno = EPROTO; return -1;
    }
    *output = record.value;
    return 0;
}
}
namespace orbisfox {
int firmware_clock_gettime(int nativeId, timespec* output) {
    if (!output) { errno = EFAULT; return -1; }
    if (!bindClocks()) { errno = ENOSYS; return -1; }
    return readClock(nativeGetTime, nativeId, output);
}
}
// Installed only in the full-Gecko executable, before the SDK link archives.
// Every SDK/Rust caller and condition attribute agrees on the same clock axis.
extern "C" int clock_gettime(clockid_t id, timespec* output) {
    const int nativeId = orbisfox::firmware_clock_id(id);
    if (nativeId < 0) { errno = EINVAL; return -1; }
    return orbisfox::firmware_clock_gettime(nativeId, output);
}
extern "C" int clock_getres(clockid_t id, timespec* output) {
    const int nativeId = orbisfox::firmware_clock_id(id);
    if (nativeId < 0) { errno = EINVAL; return -1; }
    if (!bindClocks()) { errno = ENOSYS; return -1; }
    if (!output) return nativeGetRes(nativeId, nullptr); // POSIX allows a null result.
    return readClock(nativeGetRes, nativeId, output);
}
extern "C" int pthread_condattr_setclock(pthread_condattr_t* attr, clockid_t id) {
    const int nativeId = orbisfox::firmware_condition_clock_id(id);
    if (!attr || nativeId < 0) return EINVAL;
    if (!bindClocks()) return ENOSYS;
    return nativeSetConditionClock(attr, nativeId); // pthread APIs return error numbers.
}
extern "C" int pthread_condattr_getclock(const pthread_condattr_t* attr, clockid_t* output) {
    if (!attr || !output) return EINVAL;
    if (!bindClocks() || !nativeGetConditionClock) return ENOSYS;
    struct { uint64_t before; int value; uint32_t surplus; uint64_t after; }
        record{0xa5a5a5a5a5a5a5a5ULL, -1, 0xa5a5a5a5U, 0xa5a5a5a5a5a5a5a5ULL};
    static_assert(sizeof(clockid_t) == sizeof(int));
    const int result = nativeGetConditionClock(attr, &record.value);
    if (record.before != 0xa5a5a5a5a5a5a5a5ULL || record.surplus != 0xa5a5a5a5U ||
        record.after != 0xa5a5a5a5a5a5a5a5ULL) return EOVERFLOW;
    if (result) return result;
    const int sdkId = orbisfox::sdk_condition_clock_id(record.value);
    if (sdkId < 0) return EINVAL;
    *output = sdkId;
    return 0;
}
#endif // ORBISFOX_FULL_GECKO: no interposition in the preserved JS/SWGL lane.
