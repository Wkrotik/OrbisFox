// Actual Firefox AutoSQLiteLifetime and pinned SQLite, host Unix filesystem.
// Not Gecko service/XPCOM integration, Orbis ABI, cookies or networking proof.
#include "AutoSQLiteLifetime.h"
#include "sqlite3.h"
#include "orbisfox/native_fcntl.h"
#include <fcntl.h>
#include <cstdarg>
#include <cassert>
#include <cstring>
#include <cstdlib>
#include <string>
#include <unistd.h>
// Only the installer is tested here: this explicit adapter double forwards to
// HOST Linux fcntl. Real production BSD marshalling tested in its own suite.
extern "C" int orbisfox_sqlite_fcntl(int fd, int command, ...) {
    va_list args; va_start(args, command); int result;
    if (command == F_GETLK || command == F_SETLK || command == F_SETLKW) {
        struct flock* value = va_arg(args, struct flock*); result = fcntl(fd, command, value);
    } else { const int value = va_arg(args, int); result = fcntl(fd, command, value); }
    va_end(args); return result;
}
namespace orbisfox { void log(const char*, ...) {} }
static bool failInit = false;
static int initCalls = 0;
extern "C" int __real_sqlite3_initialize();
extern "C" int __wrap_sqlite3_initialize() {
    ++initCalls;
    return failInit ? SQLITE_CANTOPEN : __real_sqlite3_initialize();
}
static void sql(sqlite3* db, const char* query) {
    assert(sqlite3_exec(db, query, nullptr, nullptr, nullptr) == SQLITE_OK);
}
static std::string read(sqlite3* db) {
    sqlite3_stmt* statement = nullptr;
    assert(sqlite3_prepare_v2(db, "SELECT value FROM orbisfox_probe WHERE id=1", -1, &statement, nullptr) == SQLITE_OK);
    assert(sqlite3_step(statement) == SQLITE_ROW);
    const char* value = reinterpret_cast<const char*>(sqlite3_column_text(statement, 0));
    assert(value);
    std::string result(value);
    assert(sqlite3_finalize(statement) == SQLITE_OK);
    return result;
}
int main(int argc, char** argv) {
    const char* mode = argc > 1 ? argv[1] : "success";
    failInit = !strcmp(mode, "init-failure");
    assert(mozilla::AutoSQLiteLifetime::getInitResult() == SQLITE_MISUSE);
    {
        mozilla::AutoSQLiteLifetime owner;
        assert(initCalls == 1);
        if (!strcmp(mode, "duplicate-owner")) {
            mozilla::AutoSQLiteLifetime invalidSecondOwner;
            return 99; // Must be unreachable; genuine source's singleton check.
        }
        if (failInit) {
            assert(mozilla::AutoSQLiteLifetime::getInitResult() == SQLITE_CANTOPEN);
        } else {
            assert(mozilla::AutoSQLiteLifetime::getInitResult() == SQLITE_OK);
            assert(orbisfox::install_sqlite_file_lock_adapter());
            assert(!orbisfox::install_sqlite_file_lock_adapter()); // No duplicate initialization.
            char directory[] = "/tmp/orbisfox-sqlite-lifetime-XXXXXX";
            assert(mkdtemp(directory));
            std::string path = std::string(directory) + "/probe.sqlite";
            sqlite3* db = nullptr;
            assert(sqlite3_open(path.c_str(), &db) == SQLITE_OK);
            sql(db, "CREATE TABLE orbisfox_probe(id INTEGER PRIMARY KEY,value TEXT NOT NULL)");
            sql(db, "BEGIN IMMEDIATE");
            sql(db, "INSERT INTO orbisfox_probe VALUES(1,'OrbisFox SQLite durable probe 🦊')");
            sql(db, "COMMIT");
            assert(read(db) == "OrbisFox SQLite durable probe 🦊");
            assert(sqlite3_close(db) == SQLITE_OK); db = nullptr;
            assert(sqlite3_open(path.c_str(), &db) == SQLITE_OK);
            assert(read(db) == "OrbisFox SQLite durable probe 🦊");
            sql(db, "BEGIN IMMEDIATE");
            sql(db, "UPDATE orbisfox_probe SET value='rollback sentinel' WHERE id=1");
            sql(db, "ROLLBACK");
            assert(read(db) == "OrbisFox SQLite durable probe 🦊");
            assert(sqlite3_close(db) == SQLITE_OK);
            assert(unlink(path.c_str()) == 0); assert(rmdir(directory) == 0);
        }
    }
    assert(mozilla::AutoSQLiteLifetime::getInitResult() == SQLITE_OK);
}
