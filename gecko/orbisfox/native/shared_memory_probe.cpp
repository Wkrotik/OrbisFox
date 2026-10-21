#include "mozilla/ScopeExit.h"
#include "mozilla/ipc/SharedMemoryHandle.h"
#include "mozilla/ipc/SharedMemoryMapping.h"
#include "orbisfox/presenter.h"
#include "orbisfox/run_logs.h"
#include <errno.h>
#include <fcntl.h>
#include <orbis/libkernel.h>
#include <stdint.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>
namespace orbisfox {
namespace {
void log_pool(const char* stage) {
    if (!native_diagnostics_enabled()) return;
    size_t available = 0;
    const int32_t result = sceKernelAvailableFlexibleMemorySize(reinterpret_cast<size_t>(&available));
    log("Gecko shared-memory pool: stage=%s query=%d available=%zu", stage, result, available);
}

void describe_descriptor(const char* role, int fd) {
    struct stat info{};
    errno = 0;
    const int status = fstat(fd, &info);
    const int statError = errno;
    errno = 0;
    const int access = fcntl(fd, F_GETFL, 0);
    const int accessError = errno;
    errno = 0;
    const int flags = fcntl(fd, F_GETFD, 0);
    const int flagError = errno;
    log("Gecko shared-memory descriptor: role=%s fd=%d stat=%d stat_errno=%d "
        "bytes=%lld dev=%llu ino=%llu access=%d access_errno=%d flags=%d flags_errno=%d",
        role, fd, status, statError, static_cast<long long>(info.st_size),
        static_cast<unsigned long long>(info.st_dev), static_cast<unsigned long long>(info.st_ino),
        access, accessError, flags, flagError);
}

// Failure-only diagnostics on our synthetic fixture. Transfer the owners rather
// than peeking into HandleBase layout; no descriptor escapes or loses ownership.
// None of these observations can turn a failed Gecko gate into success.
void diagnose_readonly_failure(mozilla::ipc::shared_memory::ReadOnlyHandle& source,
                               mozilla::ipc::shared_memory::ReadOnlyHandle& clone) {
    if (!native_diagnostics_enabled()) return;
    const size_t bytes = source.Size();
    auto sourceFd = std::move(source).TakePlatformHandle();
    auto cloneFd = std::move(clone).TakePlatformHandle();
    // Explicitly release to the real deleter: fd 0 is valid, even with libc++
    // versions whose fancy-pointer reset uses an implicit integer truth test.
    const auto closeOwned = [](mozilla::UniqueFileHandle& owner) {
        if (owner) owner.get_deleter()(owner.release());
    };
    auto closeHandles = mozilla::MakeScopeExit([&] {
        closeOwned(cloneFd);
        closeOwned(sourceFd);
    });
    describe_descriptor("frozen", sourceFd.get());
    describe_descriptor("clone", cloneFd.get());
    // The earlier C SDK probe duplicated an O_RDWR anonymous object, not this
    // O_RDONLY named/unlinked object. Compare plain dup on the actual same backing.
    errno = 0;
    const int copied = dup(sourceFd.get());
    const int copyError = errno;
    log("Gecko shared-memory plain dup: source=%d result=%d errno=%d", int(sourceFd.get()), copied, copyError);
    if (copied < 0) return;
    mozilla::UniqueFileHandle copy{copied};
    auto closeCopy = mozilla::MakeScopeExit([&] { closeOwned(copy); });
    describe_descriptor("plain-dup", copy.get());
    errno = 0;
    void* mapped = mmap(nullptr, bytes, PROT_READ, MAP_SHARED, copy.get(), 0);
    const int mapError = errno;
    log("Gecko shared-memory plain-dup map: bytes=%zu address=%p failed=%d errno=%d",
        bytes, mapped, int(mapped == MAP_FAILED), mapError);
    if (mapped != MAP_FAILED) {
        errno = 0;
        const int released = munmap(mapped, bytes);
        const int releaseError = errno;
        log("Gecko shared-memory plain-dup unmap: result=%d errno=%d", released, releaseError);
        if (released != 0) __builtin_trap(); // Do not guess release of a real mapping.
    }
    log_pool("after-clone-failure");
}
}
bool probe_gecko_shared_memory() {
    using namespace mozilla::ipc::shared_memory;
    for (size_t bytes : {size_t(16384), size_t(524288)}) {
        log_pool("before-create");
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
        errno = 0;
        auto clone = frozen.Clone();
        const int cloneError = errno;
        log("Gecko shared-memory probe: clone valid=%d source-bytes=%llu clone-bytes=%llu errno=%d",
            int(bool(clone)), static_cast<unsigned long long>(frozen.Size()),
            static_cast<unsigned long long>(clone.Size()), cloneError);
        if (!clone) { log("Gecko shared-memory probe: read-only clone failed errno=%d", cloneError); return false; }
        errno = 0;
        auto readonly = frozen.Map();
        const int sourceError = errno;
        log_pool("after-source-map");
        errno = 0;
        auto second = clone.Map();
        const int mapError = errno;
        log("Gecko shared-memory probe: read-only maps valid=%d/%d source_errno=%d clone_errno=%d "
            "source-bytes=%zu clone-bytes=%zu", int(bool(readonly)), int(bool(second)),
            sourceError, mapError, readonly.Size(), second.Size());
        if (!readonly || !second || readonly.Size() != bytes || second.Size() != bytes) {
            diagnose_readonly_failure(frozen, clone);
            errno = mapError;
            return false;
        }
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
