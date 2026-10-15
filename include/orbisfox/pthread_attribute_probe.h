#pragma once
#include <stdint.h>
#include <stddef.h>
namespace orbisfox {
struct AttributeProbeResult { int init_rc; int destroy_rc; bool guard_ok; };
// Firmware attributes are pointer-sized handles. Check both sides of their
// storage after init/destroy; compiler stack protection remains enabled too.
template<class Attr>
AttributeProbeResult probe_attribute(int (*init)(Attr*), int (*destroy)(Attr*)) {
    static_assert(sizeof(Attr) == 8 && alignof(Attr) == 8, "firmware pthread attribute needs an eight-byte handle");
    struct Guarded { uint64_t before; Attr value; uint64_t after; };
    static_assert(offsetof(Guarded, value) == 8 && offsetof(Guarded, after) == 16, "no hidden padding around attribute guard");
    constexpr uint64_t sentinel = 0x73546f7261476461ULL;
    Guarded storage{sentinel, {}, sentinel};
    AttributeProbeResult result{init(&storage.value), 0, true};
    result.guard_ok = storage.before == sentinel && storage.after == sentinel;
    if (result.init_rc == 0 && result.guard_ok) {
        result.destroy_rc = destroy(&storage.value);
        result.guard_ok = storage.before == sentinel && storage.after == sentinel;
    }
    return result;
}
}
