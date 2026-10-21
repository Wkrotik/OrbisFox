// SPDX-License-Identifier: MIT
// Host doubles for the real native-SDK branch; not native timing evidence.
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <pthread.h>
#include <time.h>

static int calls, lastId, fail, corrupt;
static int homebrew_clock_read(int id, timespec* output) {
    ++calls; lastId = id;
    if (fail) { errno = fail; return -1; }
    *output = {123, corrupt == 2 ? 1000000000L : corrupt == 3 ? -1L : 456};
    if (corrupt == 1) reinterpret_cast<unsigned char*>(output)[sizeof(timespec)] = 0;
    return 0;
}
#define ORBISFOX_HOMEBREW_SDK 1
#define ORBISFOX_FULL_GECKO 1
#define clock_gettime homebrew_clock_read
#include "../src/ps4/native_clock.cpp"
#undef clock_gettime

int main() {
    // Host macro values only: actual native header IDs have a separate check.
    static_assert(orbisfox::firmware_clock_id(CLOCK_MONOTONIC) == CLOCK_MONOTONIC);
    static_assert(orbisfox::firmware_clock_id(CLOCK_PROCESS_CPUTIME_ID) == CLOCK_PROCESS_CPUTIME_ID);
    static_assert(orbisfox::firmware_condition_clock_id(CLOCK_MONOTONIC) == CLOCK_MONOTONIC);
    static_assert(orbisfox::sdk_condition_clock_id(CLOCK_MONOTONIC) == CLOCK_MONOTONIC);
    static_assert(orbisfox::firmware_clock_id(999) == -1);
    static_assert(orbisfox::firmware_condition_clock_id(CLOCK_THREAD_CPUTIME_ID) == -1);
    for (unsigned cycle = 0; cycle < 32; ++cycle) {
        calls = fail = corrupt = 0;
        timespec output{9, 99};
        assert(orbisfox::firmware_clock_gettime(4, &output) == 0);
        assert(lastId == 4 && calls == 1 && output.tv_sec == 123 && output.tv_nsec == 456);
        assert(orbisfox::firmware_clock_gettime(15, &output) == 0 && lastId == 15);
        assert(orbisfox::firmware_clock_gettime(4, nullptr) == -1 && errno == EFAULT && calls == 2);
        fail = EIO; output = {9, 99};
        assert(orbisfox::firmware_clock_gettime(4, &output) == -1 && errno == EIO);
        assert(output.tv_sec == 9 && output.tv_nsec == 99);
        fail = 0;
        for (int mode = 1; mode <= 3; ++mode) {
            corrupt = mode;
            assert(orbisfox::firmware_clock_gettime(4, &output) == -1);
            assert(errno == (mode == 1 ? EOVERFLOW : EPROTO));
            assert(output.tv_sec == 9 && output.tv_nsec == 99);
        }
    }
}
