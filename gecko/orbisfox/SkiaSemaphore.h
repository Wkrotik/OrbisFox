/* Orbis-specific Skia OS semaphore. Genuine pthread synchronization, no SDK
 * ksem handle assumptions. SkSemaphore's upstream atomic/lazy policy remains.
 * A primitive failure is fatal: returning from a failed wait breaks SkMutex.
 */
#ifndef ORBISFOX_SKIA_SEMAPHORE_H
#define ORBISFOX_SKIA_SEMAPHORE_H
#include "include/private/base/SkAssert.h"
#include <pthread.h>
#include <limits.h>
#include <atomic>
#include <stdint.h>

class OrbisSkiaSemaphore {
public:
    // Allocation-free observation of the actual OS slow path, not a claim
    // that sleeps alone force it. Used by the pre-Gecko contention gate.
    inline static std::atomic<uint64_t> creations{0}, waits{0}, sleeps{0};
    OrbisSkiaSemaphore() {
        check(pthread_mutex_init(&mutex_, nullptr), "mutex_init");
        check(pthread_cond_init(&condition_, nullptr), "cond_init");
        creations.fetch_add(1, std::memory_order_relaxed);
    }
    ~OrbisSkiaSemaphore() {
        check(pthread_cond_destroy(&condition_), "cond_destroy");
        check(pthread_mutex_destroy(&mutex_), "mutex_destroy");
    }
    OrbisSkiaSemaphore(const OrbisSkiaSemaphore&) = delete;
    OrbisSkiaSemaphore& operator=(const OrbisSkiaSemaphore&) = delete;
    void signal(int n) {
        check(pthread_mutex_lock(&mutex_), "signal_lock");
        if (n <= 0 || count_ > INT_MAX - n) {
            SK_ABORT("Orbis Skia semaphore invalid signal: count=%d n=%d", count_, n);
        }
        count_ += n;
        // Broadcast permits all n entitled waiters to compete. The predicate,
        // not the wakeup, grants a permit; spurious wakes cannot enter SkMutex.
        check(pthread_cond_broadcast(&condition_), "cond_broadcast");
        check(pthread_mutex_unlock(&mutex_), "signal_unlock");
    }
    void wait() {
        waits.fetch_add(1, std::memory_order_relaxed);
        check(pthread_mutex_lock(&mutex_), "wait_lock");
        while (count_ == 0) {
            sleeps.fetch_add(1, std::memory_order_relaxed);
            check(pthread_cond_wait(&condition_, &mutex_), "cond_wait");
        }
        --count_;
        check(pthread_mutex_unlock(&mutex_), "wait_unlock");
    }
private:
    static void check(int error, const char* operation) {
        if (error != 0) {
            SK_ABORT("Orbis Skia semaphore %s failed: pthread-error=%d", operation, error);
        }
    }
    pthread_mutex_t mutex_{};
    pthread_cond_t condition_{};
    int count_ = 0;
};
#endif
