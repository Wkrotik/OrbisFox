#include "orbisfox/native_stat.h"
#include <assert.h>
#include <string.h>
// Internal SDK layout, not a mock filesystem implementation.
struct SdkStat {
    uint32_t st_dev, st_ino, st_mode;
    uint16_t st_nlink;
    uint32_t st_uid, st_gid, st_rdev;
    timespec st_atim, st_mtim, st_ctim;
    int64_t st_size, st_blocks;
    uint32_t st_blksize, st_flags, st_gen;
    timespec st_birthtim;
};
static_assert(sizeof(SdkStat) == 128);
static_assert(offsetof(SdkStat, st_size) == 80);
int main() {
    for (unsigned i = 0; i < 32; ++i) {
        orbisfox::FirmwareStat native{};
        native.device = 0x12345678; native.inode = 0x89abcdef;
        native.mode = 0100555; native.links = 10;
        native.uid = 0x87654321; native.gid = 0x23456789; native.rdev = 0xabcdef01;
        native.accessed = {123,456}; native.modified = {234,567}; native.changed = {345,678};
        native.created = {456,789}; native.bytes = 569208; native.blocks = 1152;
        native.block_size = 16384; native.flags = 0x87654321; native.generation = 0x98765432;
        struct { unsigned char before[32]; SdkStat value; unsigned char after[32]; } result;
        memset(&result, 0xa5, sizeof(result));
        orbisfox::translate_stat(native, result.value);
        const auto& out = result.value;
        for (auto b : result.before) assert(b == 0xa5);
        for (auto b : result.after) assert(b == 0xa5);
        assert(out.st_dev == native.device && out.st_ino == native.inode);
        assert(out.st_mode == native.mode && out.st_nlink == native.links);
        assert(out.st_uid == native.uid && out.st_gid == native.gid && out.st_rdev == native.rdev);
        assert(out.st_atim.tv_sec == 123 && out.st_atim.tv_nsec == 456);
        assert(out.st_mtim.tv_sec == 234 && out.st_mtim.tv_nsec == 567);
        assert(out.st_ctim.tv_sec == 345 && out.st_ctim.tv_nsec == 678);
        assert(out.st_birthtim.tv_sec == 456 && out.st_birthtim.tv_nsec == 789);
        assert(out.st_size == 569208 && out.st_blocks == 1152);
        assert(out.st_blksize == native.block_size && out.st_flags == native.flags && out.st_gen == native.generation);
    }
}
