// SPDX-License-Identifier: MIT
// Actual pinned Mesa ralloc + actual SDK allocator objects, with Linux OS shims.
// Host-only reproduction harness: does not prove console ABI or GPU behavior.
#define ORBISFOX_SDK_ALLOCATOR_BACKEND_ONLY
#include "native_allocator_test.cpp"
#include "util/ralloc.h"
#include "orbisfox/allocator_flight.h"
#include <array>
#include <thread>
#include <vector>

extern "C" void* sdk_memcpy(void*,const void*,size_t);
extern "C" void* sdk_memset(void*,int,size_t);
extern "C" void sdk_test_advice_gate();
namespace orbisfox {
static std::atomic<bool> testCapture{false};
bool native_diagnostics_enabled() { return testCapture.load(); }
unsigned long long native_diagnostics_generation() { return 1; }
bool native_write_allocator_flight(const AllocatorFlightEvent* events,size_t count,unsigned long long run,bool){
 assert(run==1);for(size_t i=0;i<count;++i)assert(events[i].checksum==allocator_flight_checksum(events[i]));
 errno=EIO;return true; // Recorder must preserve the actual allocator's errno.
}
void native_write_heap_audit(const char* text, size_t size) { (void)write(STDERR_FILENO,text,size); }
}
static std::atomic<unsigned> destroyed{0};
static void destroyed_child(void*) { ++destroyed; }
static void dispatch_nop() {}

static void replay(unsigned index, std::atomic<void*>& outgoing,
                   std::atomic<void*>& incoming) {
  const unsigned char pattern = static_cast<unsigned char>(index + 1);
  std::array<unsigned char, 13112> payload;
  payload.fill(pattern);
  for (unsigned cycle = 0; cycle < 128; ++cycle) {
    void* root = ralloc_context(nullptr); assert(root);
    void* compiler = ralloc_context(root); assert(compiler);
    void* moved = ralloc_context(root); assert(moved);
    ralloc_set_destructor(moved, destroyed_child);
    char* text = ralloc_strdup(root, "shader"); assert(text);
    for (unsigned j = 0; j < 64; ++j) {
      assert(ralloc_strcat(&text, "_key_presses"));
      assert(strlen(text) == 6 + (j + 1) * 12);
    }
    for (unsigned j = 0; j < 32; ++j) {
      const size_t initial = j % 4 ? 13112 + j * 16 : 262144;
      auto* data = static_cast<unsigned char*>(ralloc_size(compiler, initial)); assert(data);
      sdk_memset(data, pattern, initial);
      const size_t smaller = j % 4 ? 32 + j * 16 : 50201;
      data = static_cast<unsigned char*>(reralloc_size(compiler, data, smaller)); assert(data);
      for (size_t k = 0; k < smaller; ++k) assert(data[k] == pattern);
      data = static_cast<unsigned char*>(reralloc_size(compiler, data, 32768 + smaller)); assert(data);
      for (size_t k = 0; k < smaller; ++k) assert(data[k] == pattern);
      assert(sdk_memcpy(data, payload.data(), payload.size()) == data);
      assert(memcmp(data, payload.data(), payload.size()) == 0);
      if (j % 2) ralloc_free(data);
      else { ralloc_steal(moved, data); assert(ralloc_parent(data) == moved); }
    }
    // Use the same byte count and pointer-fill pattern as the observed dispatch table.
    using Proc = void(*)();
    Proc* table = static_cast<Proc*>(__wrap_malloc(13112)); assert(table);
    assert(__wrap_malloc_usable_size(table) >= 13112);
    for (size_t k = 0; k < 1639; ++k) table[k] = dispatch_nop;
    for (size_t k = 0; k < 1639; ++k) assert(table[k] == dispatch_nop);
    __wrap_free(table);
    ralloc_free(compiler);
    assert(ralloc_parent(moved) == root);
    ralloc_free(root);
  }
  void* transfer = ralloc_context(nullptr); assert(transfer);
  auto* child = static_cast<unsigned char*>(ralloc_size(transfer, 13112)); assert(child);
  sdk_memcpy(child, payload.data(), payload.size());
  ralloc_set_destructor(child, destroyed_child);
  outgoing.store(transfer);
  void* received = nullptr;
  while (!(received = incoming.exchange(nullptr))) std::this_thread::yield();
  // Transfer ownership, never mutate a shared ralloc parent concurrently.
  ralloc_free(received);
}

int main() {
  assert(orbisfox::initialize_native_allocator_lock());
  sdk_test_thread_flag(std::getenv("SDK_TEST_BIN_LOCKS") ? 1 : 0);
  sdk_test_advice_gate();
  // Mesa requests broader endpoints only while capture is enabled, not a new flag.
  // These checks still do not inspect interior bin nodes.
  orbisfox::configure_native_allocator_bin_audit(false);
  orbisfox::configure_native_allocator_mesa_boundary_audit();
  orbisfox::testCapture = std::getenv("SDK_TEST_RUNTIME_LOGGING") != nullptr;
  std::atomic<void*> mailboxes[8]{};
  std::thread workers[8];
  for (unsigned i = 0; i < 8; ++i)
    workers[i] = std::thread(replay, i, std::ref(mailboxes[i]), std::ref(mailboxes[(i+7)%8]));
  for (auto& worker : workers) worker.join();
  assert(destroyed == 8 * 129);
  assert(orbisfox::native_allocator_audited_arena_count() > 0);
  printf("Pinned Mesa ralloc + SDK: 8 workers x128 roots, actual copy/fill/shrink/reparent/free/handoff PASS; Linux OS shims, not firmware proof\n");
}
