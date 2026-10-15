#include "orbisfox/presenter.h"
#include "orbisfox/run_logs.h"
#include "orbisfox/pthread_attribute_probe.h"
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace orbisfox {
static FILE* logfile = nullptr;
#ifdef ORBISFOX_FULL_GECKO
static pthread_mutex_t logMutex=PTHREAD_MUTEX_INITIALIZER;
static unsigned long long logGeneration=0;
struct LogLock {LogLock(){if(pthread_mutex_lock(&logMutex))__builtin_trap();}~LogLock(){if(pthread_mutex_unlock(&logMutex))__builtin_trap();}};
#endif
void log(const char* format, ...) {
#ifdef ORBISFOX_FULL_GECKO
    LogLock lock;
    if(!native_diagnostics_enabled()){if(logfile)fclose(logfile);logfile=nullptr;return;}
    const auto current=native_diagnostics_generation();
    if(current!=logGeneration){if(logfile)fclose(logfile);logfile=fopen(NativeRunLogPath("platform-layout.log").c_str(),"a");logGeneration=current;}
#endif
    va_list args;
    va_start(args, format);
    vfprintf(stdout, format, args); fputc('\n', stdout);
    va_end(args);
    if (logfile) {
        va_start(args, format);
        vfprintf(logfile, format, args); fputc('\n', logfile); fflush(logfile);
        va_end(args);
    }
}
void close_log() {
#ifdef ORBISFOX_FULL_GECKO
    LogLock lock;logGeneration=0;
#endif
    if (logfile) fclose(logfile); logfile = nullptr;
}
static void* thread_probe(void* value) { return value; }
Diagnostics run_platform_probes(bool videoout_only) {
    Diagnostics d{"NOT INITIALIZED", "FAILED", "FAILED", "UNAVAILABLE", "UNAVAILABLE", ""};
    // No log path on USB and no privileged directory writes.
    if (mkdir("/data/orbisfox", 0700) == 0 || errno == EEXIST) {
#ifdef ORBISFOX_FULL_GECKO
        if(native_diagnostics_enabled()){logfile = fopen(NativeRunLogPath("platform-layout.log").c_str(), "a");logGeneration=native_diagnostics_generation();}
#else
        logfile = fopen(videoout_only ? "/data/orbisfox/platform-videoout.log"
                                      : "/data/orbisfox/platform.log", "w");
#endif
        if (logfile) d.storage = "WRITABLE LOG";
    }
#ifdef ORBISFOX_FULL_GECKO
    if(!native_diagnostics_enabled())d.storage="DIAGNOSTICS OFF";
    log("OrbisFox 0.68 - diagnostic logging enabled");
#else
    log("OrbisFox 0.11 engine bring-up - SpiderMonkey included; Gecko HTML layout NOT included");
#endif
    log("Build mode: %s", videoout_only ? "VIDEOOUT ONLY - NO PIGLET LOADING" : "VIDEOOUT DEFAULT / PIGLET OPT-IN");
    pthread_t worker;
    int token = 42;
    void* returned = nullptr;
    int rc = pthread_create(&worker, nullptr, thread_probe, &token);
    if (rc == 0) {
        rc = pthread_join(worker, &returned);
        if (rc == 0 && returned == &token) d.threads = "CREATE / JOIN OK";
    }
    log("pthread probe: %s (rc=%d)", d.threads, rc);
    const AttributeProbeResult attributes[] = {
        probe_attribute<pthread_mutexattr_t>(pthread_mutexattr_init, pthread_mutexattr_destroy),
        probe_attribute<pthread_condattr_t>(pthread_condattr_init, pthread_condattr_destroy),
        probe_attribute<pthread_rwlockattr_t>(pthread_rwlockattr_init, pthread_rwlockattr_destroy),
    };
    const char* names[] = {"mutex", "condition", "rwlock"};
    for (size_t i = 0; i < 3; ++i) {
        const auto& p = attributes[i];
        log("pthread %s attribute: 8-byte handle / init=%d destroy=%d guard=%s",
            names[i], p.init_rc, p.destroy_rc, p.guard_ok ? "OK" : "CORRUPTED");
        if (p.init_rc || p.destroy_rc || !p.guard_ok) d.threads = "ATTRIBUTE ABI PROBE FAILED";
    }
    // Test permission transition only. Never execute unverified generated code.
    // Passing this does not prove SpiderMonkey's JIT or W^X aliases will work.
    constexpr size_t page = 16 * 1024;
    void* mapped = mmap(nullptr, page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (mapped != MAP_FAILED) {
        memset(mapped, 0, page);
        rc = mprotect(mapped, page, PROT_READ | PROT_EXEC);
        if (rc == 0) d.memory = "PERMISSION CHANGE OK";
        else log("mprotect RX failed: errno=%d", errno);
        munmap(mapped, page);
    } else log("mmap failed: errno=%d", errno);
    log("RW to RX probe: %s - JIT EXECUTION NOT TESTED", d.memory);
    int random = open("/dev/urandom", O_RDONLY);
    if (random >= 0) {
        uint8_t data[32];
        size_t done = 0;
        while (done < sizeof(data)) {
            ssize_t n = read(random, data + done, sizeof(data) - done);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) break;
            done += (size_t)n;
        }
        if (done == sizeof(data)) d.entropy = "DEVICE READ OK";
        close(random);
    }
    log("Entropy probe: %s - NO FALLBACK PRNG", d.entropy);
    log("Storage probe: %s", d.storage);
    return d;
}
} // namespace orbisfox
