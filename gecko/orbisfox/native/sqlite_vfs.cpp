#include "sqlite3.h"
#include "orbisfox/native_fcntl.h"
#include "orbisfox/presenter.h"
namespace orbisfox {
bool install_sqlite_file_lock_adapter() {
    // Pinned SQLite Unix variants share aSyscall, and derived mozStorage VFSes
    // retain those Unix xLock methods. Use the supported syscall override API,
    // never replace the VFS with a no-lock or memory-only implementation.
    sqlite3_vfs* normal = sqlite3_vfs_find("unix");
    sqlite3_vfs* exclusive = sqlite3_vfs_find("unix-excl");
    if (!normal || !exclusive || normal->iVersion < 3 || exclusive->iVersion < 3 ||
        !normal->xSetSystemCall || !normal->xGetSystemCall || !exclusive->xGetSystemCall) {
        log("ERROR: SQLite real Unix VFS syscall API unavailable"); return false;
    }
    const auto adapter = reinterpret_cast<sqlite3_syscall_ptr>(orbisfox_sqlite_fcntl);
    const auto original = normal->xGetSystemCall(normal, "fcntl");
    if (!original || original == adapter) {
        log("ERROR: SQLite file-lock syscall registration absent or duplicated"); return false;
    }
    const int result = normal->xSetSystemCall(normal, "fcntl", adapter);
    const bool ok = result == SQLITE_OK && normal->xGetSystemCall(normal, "fcntl") == adapter &&
        exclusive->xGetSystemCall(exclusive, "fcntl") == adapter;
    log("SQLite Unix/Unix-excl real fcntl syscall adapter: %s register=%d; global SDK/Rust fcntl unchanged",
        ok ? "PASS" : "FAIL", result);
    return ok;
}
}
