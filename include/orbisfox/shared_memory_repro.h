// SPDX-License-Identifier: MIT
#pragma once
// Actual POSIX shm/mmap operations, shared by host and standalone native probe.
// No anonymous/JIT/direct-memory replacement, fake successes or MAP_FIXED.
#include <errno.h>
#include <fcntl.h>
#include <initializer_list>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace orbisfox::shm_repro {
struct Segment {
  int writable = -1, readonly = -1, duplicate = -1;
  void *writeMap = MAP_FAILED, *readMap = MAP_FAILED, *duplicateMap = MAP_FAILED;
  size_t size = 0;
  FILE* output = nullptr;
  bool release() {
    bool ok = true;
    for (void** p : {&writeMap, &readMap, &duplicateMap}) {
      if (*p != MAP_FAILED) {
        if (munmap(*p, size) != 0) {
          if (output) fprintf(output, "unmap-failed addr=%p size=%zu errno=%d; no retry\n", *p, size, errno);
          ok = false;
        }
        // Never guess/retry an uncertain native release. A failed run stops;
        // any retained mapping is left to application-manager process teardown.
        *p = MAP_FAILED;
      }
    }
    for (int* fd : {&writable, &readonly, &duplicate}) {
      if (*fd >= 0) {
        if (close(*fd) != 0) {
          if (output) fprintf(output, "close-failed fd=%d errno=%d; no retry\n", *fd, errno);
          ok = false;
        }
        *fd = -1;
      }
    }
    return ok;
  }
  ~Segment() { release(); }
  Segment() = default;
  Segment(const Segment&) = delete;
  Segment& operator=(const Segment&) = delete;
};

inline void map_record(FILE* out, const char* stage, int fd, size_t size,
                       size_t offset, int prot, void* hint, void* result, int error) {
  const int saved = errno;
  struct stat st{};
  errno = 0;
  const int sr = fstat(fd, &st), se = sr == 0 ? 0 : errno;
  errno = 0;
  const int flags = fcntl(fd, F_GETFL), fe = flags >= 0 ? 0 : errno;
  fprintf(out, "map stage=%s fd=%d size=%zu offset=%zu prot=%d flags=%d hint=%p result=%p errno=%d fstat=%d stat_errno=%d file_size=%lld fd_flags=%d flags_errno=%d page=%ld\n",
          stage, fd, size, offset, prot, MAP_SHARED, hint, result, error,
          sr, se, sr == 0 ? (long long)st.st_size : -1LL, flags, fe, sysconf(_SC_PAGESIZE));
  fflush(out);
  errno = saved;
}
inline void* map(FILE* out, const char* stage, int fd, size_t size,
                 size_t offset, int prot, void* hint = nullptr) {
  errno = 0;
  void* result = mmap(hint, size, prot, MAP_SHARED, fd, static_cast<off_t>(offset));
  const int error = result == MAP_FAILED ? errno : 0;
  map_record(out, stage, fd, size, offset, prot, hint, result, error);
  errno = error;
  return result;
}
inline bool create(FILE* out, Segment& s, size_t size, unsigned serial) {
  // O_EXCL + unique process/serial; never unlink a name this probe didn't create.
  char name[96];
  snprintf(name, sizeof(name), "/org.mozilla.ipc.%d.orbis-repro.%u", int(getpid()), serial);
  s.size = size; s.output = out;
  s.writable = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
  if (s.writable < 0) { fprintf(out, "create-failed serial=%u errno=%d\n", serial, errno); return false; }
  s.readonly = shm_open(name, O_RDONLY, 0400);
  const int openError = s.readonly < 0 ? errno : 0;
  const int unlinkResult = shm_unlink(name);
  const int unlinkError = unlinkResult == 0 ? 0 : errno;
  if (s.readonly < 0 || unlinkResult != 0) {
    fprintf(out, "readonly/unlink-failed open_errno=%d unlink_errno=%d\n", openError, unlinkError); return false;
  }
  if (ftruncate(s.writable, static_cast<off_t>(size)) != 0) {
    fprintf(out, "truncate-failed size=%zu errno=%d\n", size, errno); return false;
  }
  // Same clone operation selected by the browser's public SDK headers.
#ifdef F_DUPFD_CLOEXEC
  s.duplicate = fcntl(s.readonly, F_DUPFD_CLOEXEC, 0);
#else
  s.duplicate = dup(s.readonly);
#endif
  if (s.duplicate < 0) { fprintf(out, "clone-failed errno=%d\n", errno); return false; }
  s.writeMap = map(out, "write", s.writable, size, 0, PROT_READ | PROT_WRITE);
  if (s.writeMap == MAP_FAILED) return false;
  volatile uint8_t* bytes = static_cast<volatile uint8_t*>(s.writeMap);
  for (size_t i = 0; i < size; ++i) bytes[i] = uint8_t((i * 17 + serial) & 255);
  // Freeze semantics: discard writable view and writable descriptor, retain
  // actual independent read-only descriptors opened before shm_unlink.
  void* writableView = s.writeMap; s.writeMap = MAP_FAILED;
  if (munmap(writableView, size) != 0) {
    fprintf(out, "freeze-unmap-failed errno=%d; no retry\n", errno); return false;
  }
  const int writable = s.writable; s.writable = -1;
  if (close(writable) != 0) return false;
  s.readMap = map(out, "readonly", s.readonly, size, 0, PROT_READ);
  s.duplicateMap = map(out, "clone", s.duplicate, size, 0, PROT_READ);
  if (s.readMap == MAP_FAILED || s.duplicateMap == MAP_FAILED) return false;
  const volatile uint8_t* a = static_cast<const volatile uint8_t*>(s.readMap);
  const volatile uint8_t* b = static_cast<const volatile uint8_t*>(s.duplicateMap);
  for (size_t i = 0; i < size; ++i) {
    const uint8_t expected = uint8_t((i * 17 + serial) & 255);
    if (a[i] != expected || b[i] != expected) {
      fprintf(out, "data-mismatch serial=%u offset=%zu\n", serial, i); return false;
    }
  }
  return true;
}
inline bool run(FILE* out) {
  const long page = sysconf(_SC_PAGESIZE);
  fprintf(out, "shm-repro version=1 page=%ld getpagesize=%d pressure_backing_limit=16777216\n", page, getpagesize());
  if (page <= 0 || page > 1048576) return false;
  const size_t p = size_t(page);
  unsigned serial = 0;
  const size_t sizes[] = {p, p * 2, 65536, 524288, 4194304};
  for (size_t size : sizes) {
    Segment s;
    if (!create(out, s, size, serial++)) return false;
    // Negative controls: read-only handles must not gain a shared writable
    // view; misaligned offsets must not be silently rounded down.
    void* forbidden = map(out, "expected-readonly-write-rejection", s.readonly, p, 0, PROT_READ | PROT_WRITE);
    const int readonlyError = errno;
    if (forbidden != MAP_FAILED) { munmap(forbidden, p); return false; }
    if (readonlyError != EACCES && readonlyError != EPERM) return false;
    void* misaligned = map(out, "expected-offset-rejection", s.readonly, p, 1, PROT_READ);
    const int offsetError = errno;
    if (misaligned != MAP_FAILED) { munmap(misaligned, p); return false; }
    if (offsetError != EINVAL) return false;
    if (size > p) {
      const size_t length = size - p;
      void* offsetMap = map(out, "page-offset", s.readonly, length, p, PROT_READ);
      if (offsetMap == MAP_FAILED) return false;
      const volatile uint8_t* data = static_cast<const volatile uint8_t*>(offsetMap);
      const bool equal = data[0] == uint8_t((p * 17 + serial - 1) & 255);
      if (munmap(offsetMap, length) != 0 || !equal) return false;
    }
    if (!s.release()) return false;
  }
  // Bounded live pressure: 16 MiB backing, 32 MiB read-only virtual views.
  // Stop on the first failed operation; never fill available console memory.
  for (unsigned round = 0; round < 3; ++round) {
    Segment slots[16];
    for (auto& s : slots) if (!create(out, s, 1048576, serial++)) return false;
    // Non-FIFO destruction catches descriptor and view ownership mistakes.
    for (unsigned i = 0; i < 16; ++i) if (!slots[(i * 7) % 16].release()) return false;
  }
  // Non-page-length cases last: identify native rounding restrictions without
  // preventing the production-sized and bounded-pressure tests above.
  for (size_t size : {size_t(1), p - 1, p + 1}) {
    Segment s;
    if (!create(out, s, size, serial++) || !s.release()) return false;
  }
  fprintf(out, "PASS shm-repro create/truncate/unlink/write/freeze/clone/offset/read/teardown cases=%u\n", serial);
  fflush(out);
  return true;
}
} // namespace orbisfox::shm_repro
