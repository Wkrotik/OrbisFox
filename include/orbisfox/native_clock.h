#pragma once
#include <time.h>
namespace orbisfox {
// Full-Gecko-only SDK -> firmware boundary. Public FreeBSD 9 clock semantics:
// https://github.com/freebsd/freebsd-src/blob/releng/9.0/sys/sys/time.h
// https://github.com/freebsd/freebsd-src/blob/releng/9.0/sys/kern/kern_time.c
// 0.29 firmware confirmed native 4 advances across idle sleep, native 1 does not.
// Keep SDK/Rust enums unchanged: 0=realtime, 1=monotonic, 2=process CPU, 3=thread CPU.
constexpr int firmware_clock_id(int sdk) {
    switch (sdk) {
    case 0: return 0;
    case 1: return 4;
    case 2: return 2;  // FreeBSD CLOCK_PROF includes process user + system CPU time.
    case 3: return 14;
    case 5: return 10; // realtime coarse -> FreeBSD realtime fast
    case 6: return 12; // monotonic coarse -> FreeBSD monotonic fast
    default: return -1; // No pretend RAW, BOOTTIME/suspend, alarm or TAI support.
    }
}
constexpr int firmware_condition_clock_id(int sdk) {
    return sdk == 0 ? 0 : sdk == 1 ? 4 : -1;
}
constexpr int sdk_condition_clock_id(int native) {
    return native == 0 ? 0 : native == 4 ? 1 : -1;
}
// Explicit untranslated diagnostic access, never an SDK clock API substitute.
int firmware_clock_gettime(int nativeId, struct timespec* output);
bool probe_gecko_clocks();
}
