#include "orbisfox/native_clock.h"
#include "orbisfox/presenter.h"
#include "mozilla/Monitor.h"
#include "mozilla/TimeStamp.h"
#include "mozilla/Uptime.h"
#include <pthread.h>
#include <errno.h>
#include <string.h>
#include <orbis/libkernel.h>
namespace orbisfox {
namespace {
double difference(const timespec& end, const timespec& start) {
    return double(end.tv_sec - start.tv_sec) + double(end.tv_nsec - start.tv_nsec) / 1e9;
}
struct GuardedClockAttr {
    unsigned char before[32]; pthread_condattr_t attr; unsigned char after[32];
    GuardedClockAttr() { memset(this, 0xa5, sizeof(*this)); }
    bool intact() const {
        for (auto c : before) if (c != 0xa5) return false;
        for (auto c : after) if (c != 0xa5) return false;
        return true;
    }
};
}
bool probe_gecko_clocks() {
    static_assert(CLOCK_MONOTONIC == 1 && CLOCK_THREAD_CPUTIME_ID == 3);
    static_assert(sizeof(timespec) == 16 && sizeof(pthread_condattr_t) == 8);
    timespec resolution{}, realtime{}, process{}, thread{};
    const int res = clock_getres(CLOCK_MONOTONIC, &resolution);
    const int real = clock_gettime(CLOCK_REALTIME, &realtime);
    const int cpu = clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &process);
    const int thr = clock_gettime(CLOCK_THREAD_CPUTIME_ID, &thread);
    log("Gecko clock boundary: SDK monotonic1->firmware4 process2->PROF2 thread3->14; res=%d realtime=%d process=%d thread=%d",
        res, real, cpu, thr);
    // Optional CPU queries preserve real firmware errors; only required elapsed
    // and realtime clocks are gates for this offline browser milestone.
    if (res || real || resolution.tv_sec < 0 ||
        (resolution.tv_sec == 0 && resolution.tv_nsec <= 0)) return false;
    GuardedClockAttr guarded;
    int init = pthread_condattr_init(&guarded.attr);
    if (init) { log("Gecko condition clock: init=%d", init); return false; }
    int set = pthread_condattr_setclock(&guarded.attr, CLOCK_MONOTONIC);
    clockid_t readback = -1;
    int get = pthread_condattr_getclock(&guarded.attr, &readback);
    int destroy = pthread_condattr_destroy(&guarded.attr);
    log("Gecko condition clock: init=%d set=%d get=%d sdk-readback=%d destroy=%d guards=%d",
        init, set, get, int(readback), destroy, int(guarded.intact()));
    if (set || get || destroy || readback != CLOCK_MONOTONIC || !guarded.intact()) return false;
    for (unsigned sample = 0; sample < 3; ++sample) {
        timespec before{}, after{}, nativeBefore{}, nativeAfter{};
        if (clock_gettime(CLOCK_MONOTONIC, &before) || firmware_clock_gettime(4, &nativeBefore)) return false;
        const uint64_t start = sceKernelGetProcessTime();
        const auto geckoStart = mozilla::TimeStamp::Now();
        sceKernelUsleep(100000);
        const double gecko = (mozilla::TimeStamp::Now() - geckoStart).ToSeconds();
        const double kernel = double(sceKernelGetProcessTime() - start) / 1e6;
        if (clock_gettime(CLOCK_MONOTONIC, &after) || firmware_clock_gettime(4, &nativeAfter)) return false;
        const double sdk = difference(after, before), native = difference(nativeAfter, nativeBefore);
        log("Gecko clock idle sample=%u SDK=%.6f native4=%.6f Gecko=%.6f kernel=%.6f seconds",
            sample, sdk, native, gecko, kernel);
        if (sdk < .05 || sdk > 5 || gecko < .05 || gecko > 5 ||
            sdk - kernel > .1 || kernel - sdk > .1 || gecko - kernel > .1 || kernel - gecko > .1 ||
            native - sdk > .1 || sdk - native > .1) return false;
    }
    // Exercise Gecko's unchanged actual condition implementation: the attr
    // selector and the absolute deadline must have the same elapsed-time axis.
    mozilla::Monitor monitor("OrbisClockDeadlineProbe");
    mozilla::MonitorAutoLock lock(monitor);
    const uint64_t started = sceKernelGetProcessTime();
    const auto status = lock.Wait(mozilla::TimeDuration::FromMilliseconds(200));
    const double elapsed = double(sceKernelGetProcessTime() - started) / 1e6;
    log("Gecko actual condition deadline: timeout=%d elapsed=%.6f seconds",
        int(status == mozilla::CVStatus::Timeout), elapsed);
    const auto uptimeBefore = mozilla::ProcessUptimeMs();
    sceKernelUsleep(20000);
    const auto uptimeAfter = mozilla::ProcessUptimeMs();
    const bool uptimeReady = uptimeBefore.isSome() && uptimeAfter.isSome() &&
        *uptimeAfter >= *uptimeBefore + 10 && *uptimeAfter <= *uptimeBefore + 5000;
    log("Gecko audio-session process uptime: available=%d advancing=%d",int(uptimeBefore.isSome() && uptimeAfter.isSome()),int(uptimeReady));
    const bool ok = uptimeReady && status == mozilla::CVStatus::Timeout && elapsed >= .15 && elapsed < 5;
    log("Gecko elapsed clocks / idle progression / actual condition deadline: %s", ok ? "PASS" : "FAIL");
    return ok;
}
}
