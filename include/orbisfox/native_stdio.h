#pragma once
#include <stdint.h>
namespace orbisfox {
// Full-Gecko only. SDK FILE remains opaque and its buffered implementation stays
// intact; replace just its musl-TLS-based locking with real pthread locking.
bool initialize_native_stdio_locks();
bool probe_native_stdio_locks();
uint64_t native_stdio_entry_lock_count();
}
