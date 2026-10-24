#pragma once
#include <stddef.h>
#include <stdint.h>
#include <sys/stat.h>
namespace orbisfox {
// FreeBSD 9-derived PS4 kernel record. Only the old musl-facing SDK requires
// explicit translation; the native BSD SDK must match the audited layout and
// imports its own stat/lstat/fstat without application libc interposition.
struct FirmwareStat {
    uint32_t device, inode;
    uint16_t mode, links;
    uint32_t uid, gid, rdev;
    timespec accessed, modified, changed;
    int64_t bytes, blocks;
    uint32_t block_size, flags, generation;
    int32_t spare;
    timespec created;
};
static_assert(sizeof(FirmwareStat) == 120);
static_assert(offsetof(FirmwareStat, accessed) == 24);
static_assert(offsetof(FirmwareStat, bytes) == 72);
static_assert(offsetof(FirmwareStat, created) == 104);
template<class Stat> inline void translate_stat(const FirmwareStat& native, Stat& result) {
    result = {};
    result.st_dev = native.device; result.st_ino = native.inode;
    result.st_mode = native.mode; result.st_nlink = native.links;
    result.st_uid = native.uid; result.st_gid = native.gid; result.st_rdev = native.rdev;
    result.st_atim = native.accessed; result.st_mtim = native.modified;
    result.st_ctim = native.changed; result.st_birthtim = native.created;
    result.st_size = native.bytes; result.st_blocks = native.blocks;
    result.st_blksize = native.block_size; result.st_flags = native.flags;
    result.st_gen = native.generation;
}
// Installed only in the full-Gecko executable, never the preserved 0.11 lane.
bool probe_native_filesystem_metadata();
}
