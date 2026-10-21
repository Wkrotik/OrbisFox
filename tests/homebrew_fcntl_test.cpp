// SPDX-License-Identifier: MIT
// Real native-SDK-compiled adapter linked to Linux error/firmware doubles.
// Exercises its BSD ABI, not console file exclusion or SQLite durability.
#include "orbisfox/native_fcntl.h"
#include <cassert>
#include <cerrno>
#include <cstdarg>
#include <cstring>
#include <initializer_list>
#include <cstdlib>
#include <sys/random.h>
// FreeBSD code reads a global canary, Linux libc uses TLS. Supply the test
// platform's real entropy without disabling the native object's guard checks.
extern "C" { uintptr_t __stack_chk_guard; }
__attribute__((constructor)) static void seed_canary() {
    if (getrandom(&__stack_chk_guard, sizeof(__stack_chk_guard), 0) != sizeof(__stack_chk_guard)
        || !__stack_chk_guard) std::abort();
}
using Record = orbisfox::FirmwareFlock;
static constexpr int getLock = 11, setLock = 12, waitLock = 13;
static int calls, mode, lastFd, lastCommand, lastInteger, nativeError;
// Actual BSD SDK values, independently checked with its real compiler/headers.
static constexpr int nativeAgain = 35, nativeOverflow = 84, nativeProtocol = 92, nativeFault = 14;
static Record lastInput;
extern "C" int* homebrew_test_errno() { return &nativeError; }
namespace orbisfox { void log(const char*, ...) {} }
extern "C" int homebrew_test_fcntl(int fd, int command, ...) {
    ++calls; lastFd = fd; lastCommand = command;
    va_list args; va_start(args, command);
    if (command == getLock || command == setLock || command == waitLock) {
        auto* value = va_arg(args, Record*); va_end(args);
        assert(value); lastInput = *value;
        if (mode == 1) { value->type = 99; nativeError = nativeAgain; return -1; }
        if (mode == 2) { reinterpret_cast<unsigned char*>(value)[sizeof(Record)] = 0; return 0; }
        if (command == getLock) {
            value->type = mode == 3 ? 99 : 2;
            value->sysid = mode == 4 ? 1 : 0;
            value->pid = 123;
        }
    } else {
        lastInteger = va_arg(args, int); va_end(args);
    }
    return 0;
}
int main() {
    for (unsigned cycle = 0; cycle < 32; ++cycle) {
        mode = calls = 0;
        Record original{17, 33, 0, 3, 0, 0, 0}, value = original;
        assert(orbisfox_sqlite_fcntl(17, getLock, &value) == 0);
        assert(lastFd == 17 && lastCommand == getLock && calls == 1);
        assert(std::memcmp(&lastInput, &original, sizeof(original)) == 0);
        assert(value.type == 2 && value.pid == 123 && value.start == 17 && value.length == 33);
        value = original;
        assert(orbisfox_sqlite_fcntl(17, setLock, &value) == 0 && lastInput.type == 3);
        assert(std::memcmp(&value, &original, sizeof(value)) == 0);
        assert(orbisfox_sqlite_fcntl(17, waitLock, &value) == 0 && lastCommand == waitLock);
        assert(orbisfox_sqlite_fcntl(17, getLock, nullptr) == -1 && nativeError == nativeFault && calls == 3);
        for (int failure = 1; failure <= 4; ++failure) {
            mode = failure; value = original;
            assert(orbisfox_sqlite_fcntl(17, getLock, &value) == -1);
            assert(nativeError == (failure == 1 ? nativeAgain : failure == 2 ? nativeOverflow : nativeProtocol));
            assert(std::memcmp(&value, &original, sizeof(value)) == 0);
        }
        mode = 0;
        for (int command : {1, 3, 5}) {
            assert(orbisfox_sqlite_fcntl(17, command) == 0 && lastInteger == 0);
        }
        assert(orbisfox_sqlite_fcntl(17, 2, 77) == 0 && lastInteger == 77);
    }
}
