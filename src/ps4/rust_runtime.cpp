#define _POSIX_C_SOURCE 200809L
#include "orbisfox/rust_runtime.h"
#include "orbisfox/presenter.h"
#include <stdint.h>
#include <stddef.h>
#include <pthread.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <signal.h>
#include <dirent.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
extern "C" uint32_t orbisfox_rust_check_abi(const uint64_t*, size_t);
extern "C" uint32_t orbisfox_rust_alloc_probe();
extern "C" const uint64_t ORBISFOX_CPP_ABI[] = {
        sizeof(mode_t), sizeof(pthread_attr_t), alignof(pthread_attr_t),
        sizeof(pthread_mutex_t), alignof(pthread_mutex_t),
        sizeof(pthread_cond_t), alignof(pthread_cond_t),
        sizeof(pthread_rwlock_t), alignof(pthread_rwlock_t),
        sizeof(pthread_mutexattr_t), sizeof(pthread_condattr_t), sizeof(pthread_rwlockattr_t), sizeof(pthread_key_t),
        sizeof(struct stat), alignof(struct stat), offsetof(struct stat, st_mode), offsetof(struct stat, st_uid),
        offsetof(struct stat, st_atim), offsetof(struct stat, st_size), offsetof(struct stat, st_birthtim),
        sizeof(struct timespec), sizeof(sigset_t), sizeof(struct sigaction), offsetof(struct sigaction, sa_mask),
        sizeof(struct dirent), offsetof(struct dirent, d_name),
        EAGAIN, MAP_ANON, CLOCK_MONOTONIC, O_CREAT, O_CLOEXEC, AF_INET6
    };
namespace orbisfox {
bool probe_rust_runtime() {
    log("Rust runtime: checking SDK ABI layouts/constants begin");
    uint32_t mismatch = orbisfox_rust_check_abi(ORBISFOX_CPP_ABI, sizeof(ORBISFOX_CPP_ABI) / sizeof(ORBISFOX_CPP_ABI[0]));
    if (mismatch) {
        log("Rust runtime: ABI mismatch at field %u - refusing further runtime probes", mismatch);
        return false;
    }
    log("Rust runtime: SDK ABI subset matches (not an exhaustive ABI certification)");
    log("Rust runtime: Vec/String allocation and UTF-8 begin");
    uint32_t result = orbisfox_rust_alloc_probe();
    log("Rust runtime: allocation/UTF-8 %s", result == 1 ? "OK" : "FAILED");
    return result == 1;
}
}
