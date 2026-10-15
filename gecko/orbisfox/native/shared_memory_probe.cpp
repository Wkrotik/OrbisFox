#include "mozilla/ipc/SharedMemoryHandle.h"
#include "mozilla/ipc/SharedMemoryMapping.h"
#include "orbisfox/presenter.h"
#include <errno.h>
#include <stdint.h>
#include <utility>
namespace orbisfox {
bool probe_gecko_shared_memory() {
    using namespace mozilla::ipc::shared_memory;
    for (size_t bytes : {size_t(16384), size_t(524288)}) {
        errno = 0;
        auto handle = CreateFreezable(bytes);
        log("Gecko shared-memory probe: create bytes=%zu valid=%d errno=%d", bytes, int(bool(handle)), errno);
        if (!handle) return false;
        auto writable = std::move(handle).Map();
        log("Gecko shared-memory probe: writable map valid=%d errno=%d", int(bool(writable)), errno);
        if (!writable || writable.Size() != bytes) return false;
        for (size_t i = 0; i < bytes; ++i) writable.DataAs<uint8_t>()[i] = uint8_t((i * 17 + 93) & 255);
        auto frozen = std::move(writable).Freeze();
        log("Gecko shared-memory probe: freeze valid=%d errno=%d", int(bool(frozen)), errno);
        if (!frozen) return false;
        auto clone = frozen.Clone();
        if (!clone) { log("Gecko shared-memory probe: read-only clone failed errno=%d", errno); return false; }
        auto readonly = frozen.Map();
        auto second = clone.Map();
        log("Gecko shared-memory probe: read-only maps valid=%d/%d errno=%d", int(bool(readonly)), int(bool(second)), errno);
        if (!readonly || !second || readonly.Size() != bytes || second.Size() != bytes) return false;
        for (size_t i = 0; i < bytes; ++i) {
            const uint8_t expected = uint8_t((i * 17 + 93) & 255);
            if (readonly.DataAs<uint8_t>()[i] != expected || second.DataAs<uint8_t>()[i] != expected) {
                log("Gecko shared-memory probe: data mismatch at %zu", i); return false;
            }
        }
    }
    log("Gecko shared-memory probe: create / map / freeze / clone / immutable bytes / teardown PASS");
    return true;
}
}
