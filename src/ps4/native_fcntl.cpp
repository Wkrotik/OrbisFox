#ifdef ORBISFOX_FULL_GECKO
#include "orbisfox/native_fcntl.h"
#include "orbisfox/presenter.h"
#include <atomic>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <string.h>
#include <unistd.h>
#ifdef ORBISFOX_HOMEBREW_SDK
#include <stdlib.h>
static_assert(sizeof(struct flock) == sizeof(orbisfox::FirmwareFlock));
static_assert(offsetof(struct flock, l_type) == offsetof(orbisfox::FirmwareFlock, type));
static_assert(offsetof(struct flock, l_start) == offsetof(orbisfox::FirmwareFlock, start));
static_assert(F_RDLCK == 1 && F_WRLCK == 3 && F_UNLCK == 2);
// Keep SQLite's existing explicit syscall hook, but pass the SDK's native BSD
// records unchanged to its genuine fcntl import. No libc fcntl interposition.
extern "C" int orbisfox_sqlite_fcntl(int fd, int command, ...) {
    if (command == F_GETFD || command == F_GETFL || command == F_GETOWN)
        return fcntl(fd, command, 0);
    va_list args; va_start(args, command);
    if (command == F_GETLK || command == F_SETLK || command == F_SETLKW) {
        struct flock* argument = va_arg(args, struct flock*); va_end(args);
        if (!argument) { errno = EFAULT; return -1; }
        struct {
            unsigned char before[32]; struct flock value;
            unsigned char surplus[128], after[32];
        } record;
        memset(&record, 0xa5, sizeof(record)); record.value = *argument;
        const int result = fcntl(fd, command, &record.value);
        const auto intact = [](const auto& bytes) {
            for (auto byte : bytes) if (byte != 0xa5) return false;
            return true;
        };
        if (!intact(record.before) || !intact(record.surplus) || !intact(record.after)) {
            errno = EOVERFLOW; return -1;
        }
        if (result == -1 || command != F_GETLK) return result;
        if (record.value.l_sysid != 0 ||
            (record.value.l_type != F_RDLCK && record.value.l_type != F_WRLCK &&
             record.value.l_type != F_UNLCK)) { errno = EPROTO; return -1; }
        *argument = record.value;
        return result;
    }
    const int argument = va_arg(args, int); va_end(args);
    return fcntl(fd, command, argument);
}
namespace orbisfox {
bool probe_native_file_locks() {
    char path[] = "/data/orbisfox/fcntl-native-XXXXXX";
    const int fd = mkstemp(path);
    if (fd < 0) { log("ERROR: native file-lock probe create errno=%d", errno); return false; }
    struct flock record{}; record.l_type = F_RDLCK;
    record.l_whence = SEEK_SET; record.l_len = 1;
    const int read = orbisfox_sqlite_fcntl(fd, F_SETLK, &record);
    record.l_type = F_WRLCK;
    const int query = orbisfox_sqlite_fcntl(fd, F_GETLK, &record);
    const bool ownLockInvisible = query == 0 && record.l_type == F_UNLCK;
    record.l_type = F_WRLCK;
    const int write = orbisfox_sqlite_fcntl(fd, F_SETLKW, &record);
    record.l_type = F_UNLCK;
    const int unlock = orbisfox_sqlite_fcntl(fd, F_SETLK, &record);
    const int closed = close(fd), removed = unlink(path);
    const bool okay = read == 0 && ownLockInvisible && write == 0 && unlock == 0 && closed == 0 && removed == 0;
    log("File-lock native SDK guarded read/query/write-wait/unlock: %s results=%d/%d/%d/%d own-query-unlocked=%d close=%d remove=%d; not cross-process exclusion proof",
        okay ? "PASS" : "FAIL", read, query, write, unlock, int(ownLockInvisible), closed, removed);
    return okay;
}
}
#else
#include <orbis/libkernel.h>
namespace {
using NativeFcntl = int (*)(int, int, ...);
NativeFcntl nativeFcntl = nullptr;
constinit std::atomic<int> binding{0};
bool bind() {
    int state = binding.load(std::memory_order_acquire);
    if (state == 2) return true;
    if (state == -1) return false;
    int expected = 0;
    if (binding.compare_exchange_strong(expected, 1, std::memory_order_acq_rel)) {
        bool found = false;
        OrbisKernelModule modules[256]{}; size_t count = 0;
        if (sceKernelGetModuleList(modules, 256, &count) == 0 && count <= 256) {
            for (size_t i = 0; i < count; ++i) {
                OrbisKernelModuleInfo info{}; info.size = sizeof(info);
                if (sceKernelGetModuleInfo(modules[i], &info) != 0 ||
                    !memchr(info.name, 0, sizeof(info.name))) continue;
                const char* name = strrchr(info.name, '/'); name = name ? name + 1 : info.name;
                if (strncmp(name, "libkernel", 9) != 0) continue;
                void *address = nullptr, *low = nullptr, *high = nullptr; int32_t protection = 0;
                if (sceKernelDlsym(modules[i], "_fcntl", &address) != 0 || !address ||
                    sceKernelQueryMemoryProtection(address, &low, &high, &protection) != 0 ||
                    !(protection & ORBIS_KERNEL_PROT_CPU_EXEC) ||
                    reinterpret_cast<uintptr_t>(address) < reinterpret_cast<uintptr_t>(low) ||
                    reinterpret_cast<uintptr_t>(address) >= reinterpret_cast<uintptr_t>(high)) continue;
                nativeFcntl = reinterpret_cast<NativeFcntl>(address); found = true; break;
            }
        }
        binding.store(found ? 2 : -1, std::memory_order_release); return found;
    }
    while ((state = binding.load(std::memory_order_acquire)) == 1) __asm__ volatile("pause");
    return state == 2;
}
struct Guarded {
    unsigned char before[32];
    orbisfox::FirmwareFlock value;
    unsigned char surplus[128], after[32];
    Guarded() { memset(this, 0xa5, sizeof(*this)); memset(&value, 0, sizeof(value)); }
    bool intact() const {
        for (auto byte : before) if (byte != 0xa5) return false;
        for (auto byte : surplus) if (byte != 0xa5) return false;
        for (auto byte : after) if (byte != 0xa5) return false;
        return true;
    }
};
bool encode(short input, int16_t& output) {
    switch (input) {
        case F_RDLCK: output = 1; return true;
        case F_WRLCK: output = 3; return true;
        case F_UNLCK: output = 2; return true;
        default: return false;
    }
}
bool decode(int16_t input, short& output) {
    switch (input) {
        case 1: output = F_RDLCK; return true;
        case 3: output = F_WRLCK; return true;
        case 2: output = F_UNLCK; return true;
        default: return false;
    }
}
int lock(int fd, int command, struct flock* sdk) {
    if (!sdk) { errno = EFAULT; return -1; }
    Guarded native;
    if (!encode(sdk->l_type, native.value.type)) { errno = EINVAL; return -1; }
    native.value.start = sdk->l_start; native.value.length = sdk->l_len;
    native.value.pid = sdk->l_pid; native.value.whence = sdk->l_whence;
    if (!bind()) { errno = ENOSYS; return -1; }
    const int result = nativeFcntl(fd, command, &native.value);
    if (!native.intact()) { errno = EOVERFLOW; return -1; }
    if (result == -1 || command != F_GETLK) return result;
    struct flock output = *sdk;
    if (native.value.sysid != 0 || !decode(native.value.type, output.l_type)) {
        errno = EPROTO; return -1;
    }
    output.l_start = native.value.start; output.l_len = native.value.length;
    output.l_pid = native.value.pid; output.l_whence = native.value.whence;
    *sdk = output; return result;
}
}
// SQLite's C Unix VFS alone uses the SDK's Linux-shaped flock. Rust's
// libc uses a BSD-shaped flock already, so global fcntl interposition would
// corrupt Rust callers. Install this only via SQLite's real xSetSystemCall.
extern "C" int orbisfox_sqlite_fcntl(int fd, int command, ...) {
    if (command == F_GETFD || command == F_GETFL || command == F_GETOWN)
        return fcntl(fd, command, 0);
    va_list args; va_start(args, command);
    if (command == F_GETLK || command == F_SETLK || command == F_SETLKW) {
        struct flock* argument = va_arg(args, struct flock*); va_end(args);
        return lock(fd, command, argument);
    }
    const int argument = va_arg(args, int); va_end(args);
    return fcntl(fd, command, argument);
}
namespace orbisfox {
bool probe_native_file_locks() {
    if (!bind()) { log("ERROR: native file-lock binding unavailable"); return false; }
    static_assert(F_GETLK == 11 && F_SETLK == 12 && F_SETLKW == 13);
    static_assert(sizeof(struct flock) == 32 && offsetof(struct flock, l_type) == 0);
    const int fd = open("/data/orbisfox/fcntl-abi-probe.dat", O_CREAT | O_RDWR | O_TRUNC, 0600);
    if (fd < 0) { log("ERROR: file-lock probe open errno=%d", errno); return false; }
    struct flock sdk{}; sdk.l_type = F_RDLCK; sdk.l_whence = SEEK_SET; sdk.l_len = 1;
    errno = 0;
    // Intentionally raw, guarded SDK input to expose the former mismatch.
    // F_SETLK consumes the record and must not write it.
    struct Raw { unsigned char before[32]; struct flock value; unsigned char after[128]; } raw;
    memset(&raw, 0xa5, sizeof(raw)); raw.value = sdk;
    const int legacy = nativeFcntl(fd, F_SETLK, &raw.value), legacyErrno = errno;
    bool rawIntact = true;
    for (auto byte : raw.before) rawIntact &= byte == 0xa5;
    for (auto byte : raw.after) rawIntact &= byte == 0xa5;
    FirmwareFlock release{}; release.type = 2; release.whence = SEEK_SET;
    const int rawRelease = nativeFcntl(fd, F_SETLK, &release);
    const int read = orbisfox_sqlite_fcntl(fd, F_SETLK, &sdk); const int readErrno = read < 0 ? errno : 0;
    sdk.l_type = F_WRLCK;
    const int query = orbisfox_sqlite_fcntl(fd, F_GETLK, &sdk); const int queryErrno = query < 0 ? errno : 0;
    const bool ownLockInvisible = query == 0 && sdk.l_type == F_UNLCK;
    sdk.l_type = F_WRLCK;
    const int write = orbisfox_sqlite_fcntl(fd, F_SETLKW, &sdk); const int writeErrno = write < 0 ? errno : 0;
    sdk.l_type = F_UNLCK;
    const int unlock = orbisfox_sqlite_fcntl(fd, F_SETLK, &sdk); const int unlockErrno = unlock < 0 ? errno : 0;
    const int closeResult = close(fd);
    const bool ok = rawIntact && legacy == -1 && legacyErrno == EINVAL && rawRelease == 0 &&
        read == 0 && ownLockInvisible && write == 0 && unlock == 0 && closeResult == 0;
    log("File-lock raw SDK/BSD comparison: SDK-size=%zu/type-offset=%zu types=%d/%d/%d native-size=%zu/type-offset=%zu raw=%d errno=%d guarded=%d release=%d",
        sizeof(struct flock), offsetof(struct flock,l_type), F_RDLCK,F_WRLCK,F_UNLCK,
        sizeof(FirmwareFlock), offsetof(FirmwareFlock,type), legacy,legacyErrno,int(rawIntact),rawRelease);
    log("File-lock translated read/query/write-wait/unlock: %s results=%d/%d/%d/%d errno=%d/%d/%d/%d own-query-unlocked=%d close=%d",
        ok ? "PASS" : "FAIL",read,query,write,unlock,readErrno,queryErrno,writeErrno,unlockErrno,int(ownLockInvisible),closeResult);
    return ok;
}
}
#endif // ORBISFOX_HOMEBREW_SDK
#endif // ORBISFOX_FULL_GECKO
