// SPDX-License-Identifier: MIT
// Actual pinned C++ guard, host pthreads and an explicit native-ID double.
#define TESTING_CXA_GUARD
#include "cxa_guard_impl.h"
#include <atomic>
#include <cassert>
#include <pthread.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

static int forcedID = -1;
extern "C" int pthread_getthreadid_np(void) {
    return forcedID >= 0 ? forcedID : static_cast<int>(syscall(SYS_gettid));
}
using Guard = __cxxabiv1::SelectedImplementation;
static_assert(+__cxxabiv1::PlatformThreadID != nullptr);
struct Round {
    alignas(8) uint64_t guard = 0;
    std::atomic<unsigned> entries{0}, ready{0};
    std::atomic<bool> start{false};
    uint32_t ids[4]{};
};
struct Worker { Round* round; unsigned index; };
static void* worker(void* opaque) {
    auto& w = *static_cast<Worker*>(opaque);
    auto& r = *w.round;
    r.ids[w.index] = __cxxabiv1::PlatformThreadID();
    r.ready.fetch_add(1);
    while (!r.start.load()) usleep(100);
    Guard guard(&r.guard);
    if (guard.cxa_guard_acquire() == __cxxabiv1::INIT_IS_PENDING) {
        r.entries.fetch_add(1);
        usleep(10000);
        guard.cxa_guard_release();
    }
    return nullptr;
}
int main() {
    rlimit core{0, 0};
    assert(setrlimit(RLIMIT_CORE, &core) == 0);
    for (unsigned cycle = 0; cycle < 32; ++cycle) {
        Round round;
        pthread_t threads[4]{};
        Worker workers[4]{};
        for (unsigned i = 0; i < 4; ++i) {
            workers[i] = {&round, i};
            assert(pthread_create(&threads[i], nullptr, worker, &workers[i]) == 0);
        }
        while (round.ready.load() != 4) usleep(100);
        round.start.store(true);
        for (auto thread : threads) assert(pthread_join(thread, nullptr) == 0);
        assert(round.entries.load() == 1);
        for (unsigned i = 0; i < 4; ++i)
            for (unsigned j = i + 1; j < 4; ++j) assert(round.ids[i] != round.ids[j]);
        alignas(8) uint64_t reset = 0;
        Guard aborted(&reset);
        assert(aborted.cxa_guard_acquire() == __cxxabiv1::INIT_IS_PENDING);
        aborted.cxa_guard_abort();
        Guard retried(&reset);
        assert(retried.cxa_guard_acquire() == __cxxabiv1::INIT_IS_PENDING);
        retried.cxa_guard_release();
        // No handler in production; the host fixture observes genuine aborts.
        for (unsigned invalidID = 0; invalidID < 2; ++invalidID) {
            const pid_t child = fork();
            assert(child >= 0);
            if (child == 0) {
                forcedID = invalidID ? 0 : -1;
                alignas(8) uint64_t recursive = 0;
                Guard owner(&recursive);
                owner.cxa_guard_acquire();
                if (!invalidID) {
                    Guard again(&recursive);
                    again.cxa_guard_acquire();
                }
                _exit(99);
            }
            int status = 0;
            assert(waitpid(child, &status, 0) == child);
            assert(WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT);
        }
    }
}
