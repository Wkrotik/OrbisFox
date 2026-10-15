// Host behavior test of the Orbis-gated POSIX mapping path; not a firmware test.
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <vector>

static size_t mapped_length;
static size_t unmapped_length;
static void* tracked_mmap(void* address, size_t length, int protection,
                          int flags, int fd, off_t offset) {
  mapped_length = length;
  return mmap(address, length, protection, flags, fd, offset);
}
static int tracked_munmap(void* address, size_t length) {
  unmapped_length = length;
  return munmap(address, length);
}
#define mmap tracked_mmap
#define munmap tracked_munmap
#include "common/linux/memory_mapped_file.cc"
#undef mmap
#undef munmap

int main() {
  const long page = sysconf(_SC_PAGESIZE);
  assert(page > 0);
  char path[] = "/tmp/orbisfox-gecko-mapping-XXXXXX";
  const int fd = mkstemp(path);
  assert(fd >= 0);
  const size_t size = static_cast<size_t>(page) * 4 + 37;
  std::vector<uint8_t> bytes(size);
  for (size_t i = 0; i < size; ++i) bytes[i] = static_cast<uint8_t>(i % 251);
  size_t written = 0;
  while (written < size) {
    const ssize_t result = write(fd, bytes.data() + written, size - written);
    assert(result > 0);
    written += static_cast<size_t>(result);
  }

  google_breakpad::MemoryMappedFile mapping;
  assert(mapping.Map(path, 0));
  assert(mapping.size() == size && mapping.data());
  const auto* data = static_cast<const uint8_t*>(mapping.data());
  assert(data[0] == bytes[0] && data[size - 1] == bytes[size - 1]);
  mapping.Unmap();
  assert(mapped_length == unmapped_length);
  mapping.Unmap();
  assert(!mapping.data() && mapping.size() == 0);

  const size_t offset = static_cast<size_t>(page) * 2;
  for (int iteration = 0; iteration < 32; ++iteration) {
    assert(mapping.Map(path, offset));
    assert(mapped_length == size - offset);
    assert(mapping.size() == size - offset);
    data = static_cast<const uint8_t*>(mapping.data());
    assert(data[0] == bytes[offset]);
    assert(data[mapping.size() - 1] == bytes[size - 1]);
    mapping.Unmap();
    assert(unmapped_length == mapped_length);
  }
  assert(!mapping.Map(path, 1)); // Unaligned native offset is rejected by mmap.
  assert(!mapping.data() && mapping.size() == 0);
  assert(mapping.Map(path, size));
  assert(!mapping.data() && mapping.size() == 0);
  assert(mapping.Map(path, size + 1));
  assert(!mapping.data() && mapping.size() == 0);
  assert(mapping.Map(path, 0));
  assert(!mapping.Map("/tmp/orbisfox-missing-directory/file", 0));
  assert(!mapping.data() && mapping.size() == 0);
  assert(ftruncate(fd, 0) == 0);
  assert(mapping.Map(path, 0));
  assert(!mapping.data() && mapping.size() == 0);
  assert(close(fd) == 0);
  assert(unlink(path) == 0);
}
