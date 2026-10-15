// Actual native clock adapter, with explicit firmware/module/symbol doubles.
// Public SDK names are renamed only in this host TU; sanitizer/libc clocks
// retain their real symbols. No firmware, clock accuracy or Gecko certification.
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <thread>
#include <vector>
#include <pthread.h>
#include <time.h>
#include <orbis/libkernel.h>
static std::atomic<int> lastClock{-1}, reads{0}, lists{0};
static int nativeError = 0, corrupt = 0, resolutionNulls = 0, attrError = 0;
static int conditionClock = 0;
static bool unavailable = false, missingGetter = false, nonExecutable = false;
static int fakeRead(int id, timespec* output) {
    lastClock = id; ++reads;
    if (nativeError) { errno = nativeError; return -1; }
    if (!output) { ++resolutionNulls; return 0; }
    *output = {1000, corrupt == 2 ? 1000000000L : 123456789L};
    if (corrupt == 1) reinterpret_cast<unsigned char*>(output)[sizeof(timespec)] = 0;
    return 0;
}
static int fakeSet(pthread_condattr_t*, int id) {
    if (attrError) return attrError;
    conditionClock = id; return 0;
}
static int fakeGet(const pthread_condattr_t*, int* output) {
    if (attrError) return attrError;
    *output = conditionClock; return 0;
}
int sceKernelGetModuleList(OrbisKernelModule* output, size_t, size_t* count) {
    ++lists;
    if (unavailable) return -1;
    output[0] = 5; *count = 1; return 0;
}
int sceKernelGetModuleInfo(OrbisKernelModule, OrbisKernelModuleInfo* info) {
    strcpy(info->name, "/system/libkernel.sprx"); return 0;
}
int sceKernelDlsym(OrbisKernelModule, const char* name, void** out) {
    if (!strcmp(name, "clock_gettime") || !strcmp(name, "clock_getres")) *out = reinterpret_cast<void*>(fakeRead);
    else if (!strcmp(name, "pthread_condattr_setclock")) *out = reinterpret_cast<void*>(fakeSet);
    else if (!strcmp(name, "pthread_condattr_getclock") && !missingGetter) *out = reinterpret_cast<void*>(fakeGet);
    else return -1;
    return 0;
}
int sceKernelQueryMemoryProtection(const void*, void** low, void** high, int32_t* protection) {
    *low = reinterpret_cast<void*>(1); *high = reinterpret_cast<void*>(UINTPTR_MAX);
    *protection = nonExecutable ? 0 : ORBIS_KERNEL_PROT_CPU_EXEC; return 0;
}
#define ORBISFOX_FULL_GECKO 1
#define clock_gettime orbis_test_clock_gettime
#define clock_getres orbis_test_clock_getres
#define pthread_condattr_setclock orbis_test_condattr_setclock
#define pthread_condattr_getclock orbis_test_condattr_getclock
#include "actual-native-clock.inc"
#undef clock_gettime
#undef clock_getres
#undef pthread_condattr_setclock
#undef pthread_condattr_getclock
static void reset() {
    clockBinding.store(0); nativeGetTime = nativeGetRes = nullptr;
    nativeSetConditionClock = nullptr; nativeGetConditionClock = nullptr;
    lastClock = -1; reads = 0; lists = 0; nativeError = corrupt = resolutionNulls = attrError = 0;
    conditionClock = 0; unavailable = missingGetter = nonExecutable = false;
}
int main() {
    for (unsigned cycle = 0; cycle < 32; ++cycle) {
        reset(); timespec output{9, 99};
        const int ids[] = {0, 1, 2, 3, 5, 6};
        const int nativeIds[] = {0, 4, 2, 14, 10, 12};
        for (unsigned i = 0; i < 6; ++i) {
            assert(orbis_test_clock_gettime(ids[i], &output) == 0);
            assert(lastClock == nativeIds[i]); assert(output.tv_sec == 1000 && output.tv_nsec == 123456789);
            assert(orbis_test_clock_getres(ids[i], &output) == 0 && lastClock == nativeIds[i]);
        }
        assert(lists == 1);
        for (int id : {-1, 4, 7, 8, 9, 10, 11, 999}) {
            int count = reads; output = {9, 99}; errno = 0;
            assert(orbis_test_clock_gettime(id, &output) == -1 && errno == EINVAL);
            assert(output.tv_sec == 9 && output.tv_nsec == 99 && reads == count);
            assert(orbis_test_clock_getres(id, &output) == -1 && errno == EINVAL);
        }
        assert(orbis_test_clock_gettime(1, nullptr) == -1 && errno == EFAULT);
        assert(orbis_test_clock_getres(1, nullptr) == 0 && resolutionNulls == 1 && lastClock == 4);
        nativeError = EIO; output = {9, 99};
        assert(orbis_test_clock_gettime(1, &output) == -1 && errno == EIO);
        assert(output.tv_sec == 9 && output.tv_nsec == 99); nativeError = 0;
        for (int mode : {1, 2}) {
            corrupt = mode; output = {9, 99};
            assert(orbis_test_clock_gettime(1, &output) == -1);
            assert(errno == (mode == 1 ? EOVERFLOW : EPROTO));
            assert(output.tv_sec == 9 && output.tv_nsec == 99);
        }
        corrupt = 0;
        pthread_condattr_t attr{}; clockid_t clock = -1;
        for (int id : {0, 1}) {
            assert(orbis_test_condattr_setclock(&attr, id) == 0);
            assert(conditionClock == (id == 0 ? 0 : 4));
            assert(orbis_test_condattr_getclock(&attr, &clock) == 0 && clock == id);
        }
        for (int id : {2, 3, 4, 5, 6, -1}) assert(orbis_test_condattr_setclock(&attr, id) == EINVAL);
        assert(orbis_test_condattr_setclock(nullptr, 1) == EINVAL);
        assert(orbis_test_condattr_getclock(nullptr, &clock) == EINVAL);
        assert(orbis_test_condattr_getclock(&attr, nullptr) == EINVAL);
        conditionClock = 1; clock = 99;
        assert(orbis_test_condattr_getclock(&attr, &clock) == EINVAL && clock == 99);
        attrError = ENOMEM;
        assert(orbis_test_condattr_setclock(&attr, 1) == ENOMEM);
        assert(orbis_test_condattr_getclock(&attr, &clock) == ENOMEM && clock == 99);
        reset(); unavailable = true;
        assert(orbis_test_clock_gettime(1, &output) == -1 && errno == ENOSYS);
        assert(orbis_test_clock_getres(1, &output) == -1 && errno == ENOSYS);
        assert(orbis_test_condattr_setclock(&attr, 1) == ENOSYS);
        assert(lists == 1); // Failure cached, no fabricated clocks.
        reset(); nonExecutable = true;
        assert(orbis_test_clock_gettime(1, &output) == -1 && errno == ENOSYS);
        reset(); missingGetter = true;
        assert(orbis_test_clock_gettime(1, &output) == 0);
        assert(orbis_test_condattr_setclock(&attr, 1) == 0);
        assert(orbis_test_condattr_getclock(&attr, &clock) == ENOSYS);
        reset();
        std::vector<std::thread> workers;
        for (int i = 0; i < 8; ++i) workers.emplace_back([] {
            for (int j = 0; j < 100; ++j) { timespec time{};
                assert(orbis_test_clock_gettime(1, &time) == 0 && time.tv_sec == 1000); }
        });
        for (auto& worker : workers) worker.join();
        assert(lists == 1 && reads == 800);
        timespec raw{}; assert(orbisfox::firmware_clock_gettime(1, &raw) == 0 && lastClock == 1);
    }
}
