#pragma once
#include <stddef.h>
#include <stdint.h>
namespace orbisfox {
// Public FreeBSD9 sys/sys/fcntl.h layout; firmware startup probes must confirm.
struct FirmwareFlock {
    int64_t start, length;
    int32_t pid;
    int16_t type, whence;
    int32_t sysid, padding;
};
static_assert(sizeof(FirmwareFlock) == 32 && alignof(FirmwareFlock) == 8);
static_assert(offsetof(FirmwareFlock, type) == 20 && offsetof(FirmwareFlock, sysid) == 24);
bool probe_native_file_locks();
bool install_sqlite_file_lock_adapter();
}
extern "C" int orbisfox_sqlite_fcntl(int fd, int command, ...);
